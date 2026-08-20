"""运单跟踪服务 - 状态机推进 + Kanban 数据"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.tracking import (
    TRACKING_FLOW,
    TrackingEvent,
    TrackingSource,
    TrackingStatus,
)


def can_advance(from_status: TrackingStatus, to_status: TrackingStatus) -> bool:
    """是否允许从 from 推进到 to"""
    if from_status == to_status:
        return True
    return to_status in TRACKING_FLOW.get(from_status, [])


async def latest_status(db: AsyncSession, booking_id: str) -> TrackingStatus:
    """获取某个 booking 最近的跟踪状态 (没有事件时返回 BOOKED)

    用 created_at 排序 (而非 occurred_at):
    - occurred_at 是业务发生时间, 用户可能回填老时间
    - created_at 是事件入库时间, 反映真实推进顺序
    """
    stmt = (
        select(TrackingEvent)
        .where(TrackingEvent.booking_id == booking_id)
        .order_by(TrackingEvent.created_at.desc())
        .limit(1)
    )
    last = (await db.execute(stmt)).scalar_one_or_none()
    if not last:
        return TrackingStatus.BOOKED
    return last.status


async def add_event(
    db: AsyncSession,
    booking_id: str,
    status: TrackingStatus,
    occurred_at: datetime | None = None,
    location: str | None = None,
    vessel_name: str | None = None,
    voyage_no: str | None = None,
    container_no: str | None = None,
    source: TrackingSource = TrackingSource.MANUAL,
    remark: str | None = None,
    check_flow: bool = True,
) -> TrackingEvent:
    """添加一个跟踪节点"""
    # 校验状态机
    if check_flow:
        current = await latest_status(db, booking_id)
        if not can_advance(current, status):
            raise ValueError(
                f"状态推进非法: {current.value} -> {status.value} (允许: {[s.value for s in TRACKING_FLOW.get(current, [])]})"
            )

    # 验证 booking 存在
    b = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not b:
        raise ValueError(f"booking not found: {booking_id}")

    event = TrackingEvent(
        booking_id=booking_id,
        status=status,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        location=location,
        vessel_name=vessel_name,
        voyage_no=voyage_no,
        container_no=container_no,
        source=source,
        remark=remark,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    logger.info("跟踪节点添加: booking={} status={}", booking_id, status.value)

    # 钩子: 运单 completed → 自动生成应收账单 (闭环关键步骤)
    if status == TrackingStatus.COMPLETED:
        try:
            from app.services.auto_bill_service import generate_bill_on_booking_completed

            bill = await generate_bill_on_booking_completed(db, booking_id)
            if bill:
                logger.info("✅ 运单完成自动生成应收账单: bill_id={}", bill.id)
        except Exception as e:
            # 不阻塞跟踪事件保存, 但记日志
            logger.exception("自动生成应收账单失败 (booking={}): {}", booking_id, e)

    return event


async def ensure_booked(db: AsyncSession, booking_id: str) -> TrackingEvent | None:
    """确保某个 booking 至少有 BOOKED 节点 (创建时调用)"""
    existing = (
        await db.execute(
            select(TrackingEvent)
            .where(TrackingEvent.booking_id == booking_id)
            .order_by(TrackingEvent.occurred_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        return None
    return await add_event(
        db,
        booking_id=booking_id,
        status=TrackingStatus.BOOKED,
        source=TrackingSource.AUTO,
        remark="系统自动创建",
        check_flow=False,
    )


async def kanban_data(
    db: AsyncSession, carrier: str | None = None, search: str | None = None
) -> dict:
    """聚合 Kanban 看板数据 - 按状态分组的 booking 列表"""
    # 取所有 booking + 它们最近的状态
    stmt = select(Booking).order_by(Booking.created_at.desc()).limit(200)
    if carrier:
        stmt = stmt.where(Booking.carrier == carrier)
    if search:
        like = f"%{search}%"
        stmt = stmt.where((Booking.booking_no.like(like)) | (Booking.customer_name.like(like)))
    bookings = (await db.execute(stmt)).scalars().all()

    # 状态映射
    bucket: dict[TrackingStatus, list[dict]] = {s: [] for s in TrackingStatus}
    for b in bookings:
        last_status = await latest_status(db, b.id)
        # 拿最近事件 (用 created_at, 不用 occurred_at, 后者可能被回填)
        last_event = (
            await db.execute(
                select(TrackingEvent)
                .where(TrackingEvent.booking_id == b.id)
                .order_by(TrackingEvent.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        item = {
            "booking_id": b.id,
            "booking_no": b.booking_no,
            "carrier": b.carrier,
            "pol": b.pol,
            "pod": b.pod,
            "container": f"{b.container_count}x{b.container_type}",
            "customer_name": b.customer_name,
            "etd": b.etd.isoformat() if b.etd else None,
            "eta": b.eta.isoformat() if b.eta else None,
            "last_status": last_status.value,
            "last_update": last_event.occurred_at.isoformat() if last_event else b.created_at.isoformat(),
        }
        bucket[last_status].append(item)

    # 看板列顺序
    order = [
        TrackingStatus.BOOKED,
        TrackingStatus.EMPTY_PICKED_UP,
        TrackingStatus.LOADED,
        TrackingStatus.DEPARTED,
        TrackingStatus.IN_TRANSIT,
        TrackingStatus.ARRIVED,
        TrackingStatus.DELIVERED,
        TrackingStatus.COMPLETED,
        TrackingStatus.EXCEPTION,
    ]
    labels = {
        TrackingStatus.BOOKED: "已订舱",
        TrackingStatus.EMPTY_PICKED_UP: "已提箱",
        TrackingStatus.LOADED: "已装船",
        TrackingStatus.DEPARTED: "已开船",
        TrackingStatus.IN_TRANSIT: "在途",
        TrackingStatus.ARRIVED: "已到港",
        TrackingStatus.DELIVERED: "已提货",
        TrackingStatus.COMPLETED: "已完成",
        TrackingStatus.EXCEPTION: "异常",
    }
    columns = [
        {"status": s.value, "label": labels[s], "items": bucket.get(s, []), "count": len(bucket.get(s, []))}
        for s in order
    ]
    return {"columns": columns, "total": len(bookings)}
