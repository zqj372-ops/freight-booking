"""SO 收件箱 - 上传/OCR/修正/确认"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.config import settings
from app.models.booking import Booking, BookingStatus
from app.models.so import SO, SOStatus
from app.schemas.so import (
    SOListItem,
    SOListResponse,
    SORead,
    SOUpdate,
)
from app.services.booking_service import can_transition, next_booking_no
from app.services.ocr_service import ocr_file
from app.services.so_parser import parse_so_text

router = APIRouter()


def _save_upload(file: UploadFile) -> tuple[Path, int]:
    """保存上传文件到 uploads/so/ 目录, 返回 (path, size)"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename is required")
    suffix = Path(file.filename).suffix.lower() or ".bin"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    target_dir = settings.upload_dir / "so"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{timestamp}{suffix}"
    size = 0
    with target.open("wb") as f:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.upload_size_bytes:
                f.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"file too large (>{settings.max_upload_size_mb}MB)",
                )
            f.write(chunk)
    return target, size


@router.post("/upload", response_model=SORead, status_code=201)
async def upload_so(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source: str = Query("upload", description="upload / email / api"),
    source_email: str | None = None,
    source_subject: str | None = None,
    db: AsyncSession = Depends(db_session),
) -> SORead:
    """上传 PDF/图片, 自动加入 OCR 队列"""
    target, size = _save_upload(file)
    so = SO(
        source=source,
        source_email=source_email,
        source_subject=source_subject,
        file_path=str(target),
        file_name=file.filename or target.name,
        file_mime=file.content_type or "application/octet-stream",
        file_size=size,
        status=SOStatus.PENDING,
    )
    db.add(so)
    await db.commit()
    await db.refresh(so)

    # 后台跑 OCR
    background_tasks.add_task(_run_ocr, so.id, str(target))
    return SORead.model_validate(so)


async def _run_ocr(so_id: str, file_path: str) -> None:
    """后台 OCR 任务"""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            so = (await db.execute(select(SO).where(SO.id == so_id))).scalar_one_or_none()
            if not so:
                logger.error("SO 不存在: {}", so_id)
                return

            result = await ocr_file(file_path)
            so.ocr_text = result.text
            so.ocr_engine = result.engine
            so.ocr_confidence = result.confidence
            so.ocr_at = datetime.now(timezone.utc)

            if result.error:
                so.status = SOStatus.OCR_FAILED
                so.ocr_error = result.error
            else:
                # 抽取字段
                fields = parse_so_text(result.text)
                for k, v in fields.items():
                    if hasattr(so, k) and getattr(so, k) is None:
                        setattr(so, k, v)
                if fields:
                    so.extra_fields = fields
                so.status = SOStatus.OCR_DONE if result.text else SOStatus.PENDING
            await db.commit()
            logger.info("OCR 完成: so_id={} engine={} conf={}", so_id, result.engine, result.confidence)
        except Exception as e:
            logger.exception("后台 OCR 任务失败: so_id={}", so_id)
            try:
                so = (await db.execute(select(SO).where(SO.id == so_id))).scalar_one_or_none()
                if so:
                    so.status = SOStatus.OCR_FAILED
                    so.ocr_error = str(e)
                    await db.commit()
            except Exception:
                pass


@router.get("/", response_model=SOListResponse)
async def list_sos(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: SOStatus | None = Query(None, alias="status"),
    carrier: str | None = None,
    db: AsyncSession = Depends(db_session),
) -> SOListResponse:
    """SO 列表"""
    stmt = select(SO)
    count_stmt = select(func.count(SO.id))
    if status_filter:
        stmt = stmt.where(SO.status == status_filter)
        count_stmt = count_stmt.where(SO.status == status_filter)
    if carrier:
        stmt = stmt.where(SO.carrier == carrier)
        count_stmt = count_stmt.where(SO.carrier == carrier)
    total = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * page_size
    stmt = stmt.order_by(SO.created_at.desc()).offset(offset).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return SOListResponse(
        items=[SOListItem.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{so_id}", response_model=SORead)
async def get_so(so_id: str, db: AsyncSession = Depends(db_session)) -> SORead:
    so = (await db.execute(select(SO).where(SO.id == so_id))).scalar_one_or_none()
    if not so:
        raise HTTPException(status_code=404, detail="SO not found")
    return SORead.model_validate(so)


@router.patch("/{so_id}", response_model=SORead)
async def update_so(
    so_id: str,
    payload: SOUpdate,
    db: AsyncSession = Depends(db_session),
) -> SORead:
    so = (await db.execute(select(SO).where(SO.id == so_id))).scalar_one_or_none()
    if not so:
        raise HTTPException(status_code=404, detail="SO not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(so, k, v)
    await db.commit()
    await db.refresh(so)
    return SORead.model_validate(so)


@router.post("/{so_id}/reocr", response_model=SORead)
async def reocr(
    so_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(db_session),
) -> SORead:
    """重新跑 OCR"""
    so = (await db.execute(select(SO).where(SO.id == so_id))).scalar_one_or_none()
    if not so:
        raise HTTPException(status_code=404, detail="SO not found")
    so.status = SOStatus.PENDING
    so.ocr_error = None
    await db.commit()
    background_tasks.add_task(_run_ocr, so.id, so.file_path)
    await db.refresh(so)
    return SORead.model_validate(so)


@router.post("/{so_id}/confirm", response_model=SORead)
async def confirm_so(
    so_id: str,
    db: AsyncSession = Depends(db_session),
) -> SORead:
    """确认 SO -> 生成 Booking"""
    so = (await db.execute(select(SO).where(SO.id == so_id))).scalar_one_or_none()
    if not so:
        raise HTTPException(status_code=404, detail="SO not found")
    if so.status == SOStatus.CONFIRMED and so.booking_id:
        raise HTTPException(status_code=400, detail="already confirmed")
    if not so.carrier or not so.pol or not so.pod:
        raise HTTPException(status_code=400, detail="SO 缺少必填字段 (carrier/pol/pod)")

    # 生成 Booking
    booking = Booking(
        booking_no=await next_booking_no(db, so.carrier),
        carrier=so.carrier,
        pol=so.pol,
        pod=so.pod,
        etd=so.etd,
        eta=so.eta,
        cut_off=so.cut_off,
        container_type=so.container_type or "40HQ",
        container_count=so.container_count or 1,
        commodity=so.commodity,
        customer_name=so.shipper,
        status=BookingStatus.DRAFT,
        remark=f"由 SO 自动生成: {so.file_name}",
    )
    db.add(booking)
    await db.flush()
    so.booking_id = booking.id
    so.status = SOStatus.CONFIRMED
    await db.commit()
    await db.refresh(so)
    return SORead.model_validate(so)


@router.delete("/{so_id}", status_code=204)
async def delete_so(so_id: str, db: AsyncSession = Depends(db_session)) -> None:
    so = (await db.execute(select(SO).where(SO.id == so_id))).scalar_one_or_none()
    if not so:
        raise HTTPException(status_code=404, detail="SO not found")
    if so.file_path:
        Path(so.file_path).unlink(missing_ok=True)
    await db.delete(so)
    await db.commit()
