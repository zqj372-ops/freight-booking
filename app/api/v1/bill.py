"""Bill - 账单管理 + OCR"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.config import settings
from app.models.bill import Bill, BillStatus
from app.schemas.bill import (
    BillCreate,
    BillListItem,
    BillListResponse,
    BillRead,
    BillUpdate,
)
from app.services.bill_service import process_bill_ocr, save_bill_file

router = APIRouter()


@router.post("/upload", response_model=BillRead, status_code=201)
async def upload_bill(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    bill_type: str = Query("receivable"),
    booking_id: str | None = None,
    db: AsyncSession = Depends(db_session),
) -> BillRead:
    """上传账单 PDF/图片, 后台跑 OCR"""
    content = await file.read()
    if len(content) > settings.upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file too large (>{settings.max_upload_size_mb}MB)",
        )

    path, size = save_bill_file(content, file.filename or "bill.pdf")
    bill = Bill(
        bill_no="PENDING",  # OCR 后再填
        bill_type=bill_type,
        booking_id=booking_id,
        file_path=str(path),
        file_name=file.filename or path.name,
        file_mime=file.content_type or "application/octet-stream",
        file_size=size,
        status=BillStatus.UPLOADED,
    )
    db.add(bill)
    await db.commit()
    await db.refresh(bill)

    background_tasks.add_task(process_bill_ocr, bill.id)
    return BillRead.model_validate(bill)


@router.post("/", response_model=BillRead, status_code=201)
async def create_bill(
    payload: BillCreate,
    db: AsyncSession = Depends(db_session),
) -> BillRead:
    """手动创建账单 (不走 OCR)"""
    b = Bill(**payload.model_dump(), status=BillStatus.UPLOADED)
    db.add(b)
    await db.commit()
    await db.refresh(b)
    return BillRead.model_validate(b)


@router.get("/", response_model=BillListResponse)
async def list_bills(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: BillStatus | None = Query(None, alias="status"),
    bill_type: str | None = None,
    booking_id: str | None = None,
    db: AsyncSession = Depends(db_session),
) -> BillListResponse:
    stmt = select(Bill)
    count_stmt = select(func.count(Bill.id))
    if status_filter:
        stmt = stmt.where(Bill.status == status_filter)
        count_stmt = count_stmt.where(Bill.status == status_filter)
    if bill_type:
        stmt = stmt.where(Bill.bill_type == bill_type)
        count_stmt = count_stmt.where(Bill.bill_type == bill_type)
    if booking_id:
        stmt = stmt.where(Bill.booking_id == booking_id)
        count_stmt = count_stmt.where(Bill.booking_id == booking_id)
    total = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * page_size
    stmt = stmt.order_by(Bill.created_at.desc()).offset(offset).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return BillListResponse(
        items=[BillListItem.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{bill_id}", response_model=BillRead)
async def get_bill(bill_id: str, db: AsyncSession = Depends(db_session)) -> BillRead:
    b = (await db.execute(select(Bill).where(Bill.id == bill_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="bill not found")
    return BillRead.model_validate(b)


@router.patch("/{bill_id}", response_model=BillRead)
async def update_bill(
    bill_id: str,
    payload: BillUpdate,
    db: AsyncSession = Depends(db_session),
) -> BillRead:
    b = (await db.execute(select(Bill).where(Bill.id == bill_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="bill not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    await db.commit()
    await db.refresh(b)
    return BillRead.model_validate(b)


@router.post("/{bill_id}/reocr", response_model=BillRead)
async def reocr_bill(
    bill_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(db_session),
) -> BillRead:
    """重新跑 OCR"""
    b = (await db.execute(select(Bill).where(Bill.id == bill_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="bill not found")
    if not b.file_path:
        raise HTTPException(status_code=400, detail="bill 没有文件")
    b.status = BillStatus.UPLOADED
    b.ocr_error = None
    await db.commit()
    background_tasks.add_task(process_bill_ocr, b.id)
    await db.refresh(b)
    return BillRead.model_validate(b)


@router.post("/{bill_id}/confirm", response_model=BillRead)
async def confirm_bill(
    bill_id: str,
    db: AsyncSession = Depends(db_session),
) -> BillRead:
    """财务确认入账"""
    b = (await db.execute(select(Bill).where(Bill.id == bill_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="bill not found")
    b.status = BillStatus.CONFIRMED
    await db.commit()
    await db.refresh(b)
    return BillRead.model_validate(b)


@router.delete("/{bill_id}", status_code=204)
async def delete_bill(bill_id: str, db: AsyncSession = Depends(db_session)) -> None:
    b = (await db.execute(select(Bill).where(Bill.id == bill_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="bill not found")
    from pathlib import Path

    if b.file_path:
        Path(b.file_path).unlink(missing_ok=True)
    await db.delete(b)
    await db.commit()
