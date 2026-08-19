"""Tracking - 运单跟踪节点 + Kanban 看板"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.booking import Booking
from app.models.tracking import TrackingEvent, TrackingSource, TrackingStatus
from app.schemas.tracking import (
    KanbanResponse,
    TrackingEventCreate,
    TrackingEventRead,
)
from app.services.tracking_service import (
    add_event,
    ensure_booked,
    kanban_data,
    latest_status,
)

router = APIRouter()


@router.get("/kanban", response_model=KanbanResponse)
async def get_kanban(
    carrier: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(db_session),
) -> KanbanResponse:
    """Kanban 看板数据 - 9 列按状态分组"""
    data = await kanban_data(db, carrier=carrier, search=search)
    return KanbanResponse(**data)


@router.get("/bookings/{booking_id}/status")
async def get_booking_status(
    booking_id: str,
    db: AsyncSession = Depends(db_session),
) -> dict:
    """获取 booking 当前的跟踪状态"""
    b = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="booking not found")
    return {"booking_id": booking_id, "current_status": (await latest_status(db, booking_id)).value}


@router.get("/bookings/{booking_id}/events", response_model=list[TrackingEventRead])
async def list_events(
    booking_id: str,
    db: AsyncSession = Depends(db_session),
) -> list[TrackingEventRead]:
    """列出某 booking 的所有跟踪节点 (按时间正序)"""
    stmt = (
        select(TrackingEvent)
        .where(TrackingEvent.booking_id == booking_id)
        .order_by(TrackingEvent.occurred_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [TrackingEventRead.model_validate(r) for r in rows]


@router.post(
    "/bookings/{booking_id}/events",
    response_model=TrackingEventRead,
    status_code=201,
)
async def create_event(
    booking_id: str,
    payload: TrackingEventCreate,
    db: AsyncSession = Depends(db_session),
) -> TrackingEventRead:
    """手动添加跟踪节点"""
    try:
        event = await add_event(
            db,
            booking_id=booking_id,
            status=payload.status,
            occurred_at=payload.occurred_at,
            location=payload.location,
            vessel_name=payload.vessel_name,
            voyage_no=payload.voyage_no,
            container_no=payload.container_no,
            source=payload.source,
            remark=payload.remark,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TrackingEventRead.model_validate(event)


@router.post(
    "/bookings/{booking_id}/events/{event_id}/remark",
    response_model=TrackingEventRead,
)
async def add_remark(
    booking_id: str,
    event_id: str,
    remark: str,
    db: AsyncSession = Depends(db_session),
) -> TrackingEventRead:
    """给某个事件追加备注"""
    e = (
        await db.execute(
            select(TrackingEvent).where(
                TrackingEvent.id == event_id,
                TrackingEvent.booking_id == booking_id,
            )
        )
    ).scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="event not found")
    e.remark = (e.remark + "\n" + remark) if e.remark else remark
    await db.commit()
    await db.refresh(e)
    return TrackingEventRead.model_validate(e)


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    db: AsyncSession = Depends(db_session),
) -> None:
    """删除跟踪节点 (谨慎使用)"""
    e = (
        await db.execute(select(TrackingEvent).where(TrackingEvent.id == event_id))
    ).scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="event not found")
    if e.source == TrackingSource.AUTO:
        raise HTTPException(status_code=400, detail="系统自动节点不能删")
    await db.delete(e)
    await db.commit()
