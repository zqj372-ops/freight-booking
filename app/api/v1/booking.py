"""Booking - 订舱管理 + 发送邮件"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.booking import Booking, BookingStatus
from app.models.email_log import EmailLog
from app.schemas.booking import (
    BookingCreate,
    BookingListResponse,
    BookingRead,
    BookingUpdate,
)
from app.services.booking_service import can_transition, next_booking_no
from app.services.email_service import render_and_send
from app.services.tracking_service import add_event, ensure_booked
from app.models.tracking import TrackingStatus, TrackingSource

router = APIRouter()


@router.get("/", response_model=BookingListResponse)
async def list_bookings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: BookingStatus | None = Query(None, alias="status"),
    carrier: str | None = None,
    db: AsyncSession = Depends(db_session),
) -> BookingListResponse:
    stmt = select(Booking)
    count_stmt = select(func.count(Booking.id))
    if status_filter:
        stmt = stmt.where(Booking.status == status_filter)
        count_stmt = count_stmt.where(Booking.status == status_filter)
    if carrier:
        stmt = stmt.where(Booking.carrier == carrier)
        count_stmt = count_stmt.where(Booking.carrier == carrier)
    total = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * page_size
    stmt = stmt.order_by(Booking.created_at.desc()).offset(offset).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return BookingListResponse(
        items=[BookingRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=BookingRead, status_code=201)
async def create_booking(
    payload: BookingCreate,
    db: AsyncSession = Depends(db_session),
) -> BookingRead:
    b = Booking(**payload.model_dump(exclude={"booking_no"}))
    b.booking_no = payload.booking_no or await next_booking_no(db, payload.carrier)
    db.add(b)
    await db.flush()
    # 自动创建 BOOKED 跟踪节点
    await ensure_booked(db, b.id)
    await db.commit()
    await db.refresh(b)
    return BookingRead.model_validate(b)


@router.get("/{booking_id}", response_model=BookingRead)
async def get_booking(booking_id: str, db: AsyncSession = Depends(db_session)) -> BookingRead:
    b = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="booking not found")
    return BookingRead.model_validate(b)


@router.patch("/{booking_id}", response_model=BookingRead)
async def update_booking(
    booking_id: str,
    payload: BookingUpdate,
    db: AsyncSession = Depends(db_session),
) -> BookingRead:
    b = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="booking not found")
    data = payload.model_dump(exclude_unset=True)
    new_status = data.get("status")
    if new_status and not can_transition(b.status, new_status):
        raise HTTPException(
            status_code=400,
            detail=f"invalid status transition: {b.status} -> {new_status}",
        )
    for k, v in data.items():
        setattr(b, k, v)
    # 状态推进时, 自动记一笔跟踪节点 (便于看板有数据)
    if new_status:
        tracking_map = {
            BookingStatus.SUBMITTED: TrackingStatus.BOOKED,  # 已在 BOOKED
            BookingStatus.CONFIRMED: None,  # 暂不产生新节点
            BookingStatus.COMPLETED: TrackingStatus.COMPLETED,
            BookingStatus.CANCELLED: TrackingStatus.EXCEPTION,
        }
        target_tracking = tracking_map.get(new_status)
        if target_tracking:
            try:
                await add_event(
                    db,
                    booking_id=b.id,
                    status=target_tracking,
                    source=TrackingSource.AUTO,
                    remark=f"booking status -> {new_status.value}",
                )
            except ValueError:
                # 已存在, 跳过
                pass
    await db.commit()
    await db.refresh(b)
    return BookingRead.model_validate(b)


@router.post("/{booking_id}/send", response_model=BookingRead)
async def send_booking_email(
    booking_id: str,
    template_code: str = Query("booking_request", description="邮件模板 code"),
    db: AsyncSession = Depends(db_session),
) -> BookingRead:
    """用 booking_request 模板给船公司/代理发订舱邮件"""
    b = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="booking not found")

    # 收件人优先级: 代理 booking_email > carrier 默认
    to_emails: list[str] = []
    cc_emails: list[str] = []
    if b.agent and b.agent.booking_email:
        to_emails = [b.agent.booking_email]
        cc_emails = b.agent.cc_emails or []
    else:
        raise HTTPException(
            status_code=400,
            detail="未配置收件人: 请给 booking 关联 agent 并设置 booking_email",
        )

    context = {
        "booking_no": b.booking_no,
        "carrier": b.carrier,
        "pol": b.pol,
        "pod": b.pod,
        "etd": b.etd.isoformat() if b.etd else "",
        "eta": b.eta.isoformat() if b.eta else "",
        "cut_off": b.cut_off.isoformat() if b.cut_off else "",
        "container_type": b.container_type,
        "container_count": b.container_count,
        "commodity": b.commodity or "",
        "weight_kg": b.weight_kg or "",
        "volume_cbm": b.volume_cbm or "",
        "customer_name": b.customer_name or "",
        "customer_ref": b.customer_ref or "",
        "remark": b.remark or "",
        "agent_name": b.agent.name if b.agent else "",
    }
    try:
        await render_and_send(
            template_code=template_code,
            context=context,
            to_emails=to_emails,
            cc_emails=cc_emails,
            booking_id=b.id,
            db=db,
        )
        if b.status == BookingStatus.DRAFT:
            b.status = BookingStatus.SUBMITTED
            await db.commit()
            await db.refresh(b)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"邮件发送失败: {e}")
    return BookingRead.model_validate(b)


@router.delete("/{booking_id}", status_code=204)
async def delete_booking(booking_id: str, db: AsyncSession = Depends(db_session)) -> None:
    b = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="booking not found")
    await db.delete(b)
    await db.commit()
