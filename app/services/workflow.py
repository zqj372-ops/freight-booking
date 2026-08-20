"""v0.5 workflow service - stage 推导, milestone 自动 close task, exception 自动规则"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.milestone import MilestoneSource
from app.models.operational_exception import (
    ExceptionDetectedBy,
    ExceptionSeverity,
    ExceptionStatus,
)
from app.models.task import TaskStatus
from app.models._base import BusinessPhase, PhaseColor
from app.models.booking_confirmation import BookingConfirmation, BookingConfirmationStatus
from app.models.booking_request import BookingRequest
from app.models.milestone import Milestone, MilestoneCode
from app.models.operational_exception import OperationalException, ExceptionCode
from app.models.shipment import Shipment, ShipmentStage
from app.models.task import Task, TaskCode


# ========== stage 推导 (软联动, 不写回 DB) ==========


def derive_stage(milestones: Iterable[Milestone]) -> ShipmentStage:
    """从 milestone 集合推导 Shipment.stage (后端实现 9 个值)."""
    codes = {m.code for m in milestones}
    if MilestoneCode.EMPTY_RETURNED in codes:
        return ShipmentStage.COMPLETED
    if MilestoneCode.DEPARTED in codes:
        return ShipmentStage.DEPARTED
    if MilestoneCode.SI_SUBMITTED in codes or MilestoneCode.VGM_SUBMITTED in codes:
        return ShipmentStage.DOCUMENTATION
    if MilestoneCode.CONTAINER_LOADED in codes:
        return ShipmentStage.CONTAINER_OPERATION
    if MilestoneCode.CONTAINER_PICKED_UP in codes:
        return ShipmentStage.CONTAINER_OPERATION
    if MilestoneCode.BOOKING_CONFIRMATION_ACCEPTED in codes:
        return ShipmentStage.BOOKED
    if MilestoneCode.BOOKING_CONFIRMATION_RECEIVED in codes:
        return ShipmentStage.AWAITING_CONFIRMATION
    if MilestoneCode.BOOKING_REQUEST_SENT in codes:
        return ShipmentStage.BOOKING_IN_PROGRESS
    return ShipmentStage.DRAFT


# v0.5 1.5: 8 业务阶段 (UI 进度条用, 1-8 编号, 颜色规则 5 色)
_PHASE_MAP: list[tuple[set[MilestoneCode], BusinessPhase]] = [
    ({MilestoneCode.EMPTY_RETURNED}, BusinessPhase.COMPLETED),
    ({MilestoneCode.DEPARTED, MilestoneCode.ARRIVED_AT_POD, MilestoneCode.DELIVERED,
      MilestoneCode.IN_TRANSIT}, BusinessPhase.DEPARTED),  # 7 开船到港
    ({MilestoneCode.CUSTOMS_CLEARED}, BusinessPhase.CUSTOMS),  # 6 报关放行
    ({MilestoneCode.SI_SUBMITTED, MilestoneCode.VGM_SUBMITTED}, BusinessPhase.SI_BL),  # 5 补料提单
    ({MilestoneCode.CONTAINER_LOADED, MilestoneCode.CONTAINER_GATED_IN,
      MilestoneCode.CONTAINER_PICKED_UP, MilestoneCode.EMPTY_RELEASE_AVAILABLE}, BusinessPhase.PICKUP_LOAD),  # 4
    ({MilestoneCode.BOOKING_CONFIRMATION_ACCEPTED,
      MilestoneCode.BOOKING_CONFIRMATION_RECEIVED}, BusinessPhase.SO_REVIEW),  # 3
    ({MilestoneCode.BOOKING_REQUEST_SENT, MilestoneCode.BOOKING_REQUEST_ACKNOWLEDGED}, BusinessPhase.BOOKING),  # 2
]


def derive_business_phase(milestones: Iterable[Milestone]) -> BusinessPhase:
    """v0.5 1.5: 从 Milestone 集合推导 8 业务阶段 (UI 进度条用).

    返回 BusinessPhase 枚举值 (1-8). 进度条前端渲染: 当前阶段高亮, 已完成变绿, 等待外部变紫, 即将到期变黄, 逾期变红.
    """
    codes = {m.code for m in milestones}
    for trigger_codes, phase in _PHASE_MAP:
        if codes & trigger_codes:
            return phase
    return BusinessPhase.BUILD  # 1 建业务


def derive_phase_color(
    business_phase: BusinessPhase,
    next_due_at: datetime | None = None,
    has_open_exception: bool = False,
) -> PhaseColor:
    """v0.5 1.5: 推导当前阶段的 UI 颜色.

    优先级: overdue (红) > approaching_deadline (黄) > waiting_external (紫) >
             in_progress (蓝) > completed (绿) > not_started (灰)
    """
    now = datetime.now(timezone.utc)

    # 红: 逾期 (有 open exception 或 截止已过)
    if has_open_exception:
        return PhaseColor.OVERDUE

    # 黄: 即将到期 (4h 内)
    if next_due_at is not None:
        # SQLite 返回 naive datetime, 统一转 aware
        if next_due_at.tzinfo is None:
            next_due_at = next_due_at.replace(tzinfo=timezone.utc)
        if (next_due_at - now).total_seconds() < 4 * 3600:
            return PhaseColor.APPROACHING_DEADLINE

    # 蓝: 正常进行
    return PhaseColor.IN_PROGRESS


def derive_phase_progress(milestones: Iterable[Milestone]) -> float:
    """v0.5 1.5: 8 业务阶段进度 (0.0-1.0).

    简单实现: 已触发的阶段编号 / 8. 后续 v0.6 可以按业务逻辑细化.
    """
    phase = derive_business_phase(milestones)
    return round(phase.value / 8.0, 2)


# 业务阶段中文名 (UI 渲染用)
PHASE_LABELS: dict[BusinessPhase, str] = {
    BusinessPhase.BUILD: "建业务",
    BusinessPhase.BOOKING: "发订舱",
    BusinessPhase.SO_REVIEW: "收/核 SO",
    BusinessPhase.PICKUP_LOAD: "提柜装柜",
    BusinessPhase.SI_BL: "补料提单",
    BusinessPhase.CUSTOMS: "报关放行",
    BusinessPhase.DEPARTED: "开船到港",
    BusinessPhase.COMPLETED: "结案还柜",
}


# ========== milestone → task auto_close ==========


async def auto_close_tasks_for_milestone(
    db: AsyncSession,
    *,
    organization_id: str,
    shipment_id: str,
    milestone_code: MilestoneCode,
) -> list[Task]:
    """录入 milestone 时, 所有 Task.auto_close_on == milestone_code 的 pending task 自动 mark done.

    v0.5 简化: 不需要用户确认, 直接 close, 写 audit log.
    """
    stmt = select(Task).where(
        Task.organization_id == organization_id,
        Task.shipment_id == shipment_id,
        Task.auto_close_on == milestone_code,
        Task.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
    )
    tasks = (await db.execute(stmt)).scalars().all()
    now = datetime.now(timezone.utc)
    closed: list[Task] = []
    for t in tasks:
        t.status = TaskStatus.DONE
        t.completed_at = now
        t.completed_by = "system:auto_close"
        t.completed_by_name = "system"
        closed.append(t)
    if closed:
        logger.info("auto_close {} task(s) for milestone {}", len(closed), milestone_code.value)
    return closed


# ========== 业务方法: 接受 BC 时的副作用 ==========


async def on_booking_confirmation_accepted(
    db: AsyncSession,
    *,
    organization_id: str,
    shipment_id: str,
    booking_confirmation_id: str,
) -> Milestone:
    """BookingConfirmation accept 时: 创建 milestone + 关 task + 开新 task (按 ETA 算 due)."""
    # 创建 milestone
    ms = Milestone(
        organization_id=organization_id,
        shipment_id=shipment_id,
        code=MilestoneCode.BOOKING_CONFIRMATION_ACCEPTED,
        occurred_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
        source=MilestoneSource.AUTO,
        source_ref=f"booking_confirmation:{booking_confirmation_id}",
    )
    db.add(ms)
    await db.flush()

    # 关掉 confirm_so / confirm_booking task
    closed = await auto_close_tasks_for_milestone(
        db,
        organization_id=organization_id,
        shipment_id=shipment_id,
        milestone_code=MilestoneCode.BOOKING_CONFIRMATION_ACCEPTED,
    )

    # 新建 task: 录入柜号 / 提交 SI / 提交 VGM
    bc = (await db.execute(
        select(BookingConfirmation).where(BookingConfirmation.id == booking_confirmation_id)
    )).scalar_one()
    si_cutoff = bc.si_cutoff_at
    vgm_cutoff = bc.vgm_cutoff_at

    new_tasks_specs: list[tuple[TaskCode, str, datetime | None, MilestoneCode | None]] = [
        (TaskCode.ARRANGE_PICKUP, "安排提柜", bc.cy_open_at, MilestoneCode.CONTAINER_PICKED_UP),
        (TaskCode.RECORD_CONTAINER_NO, "录入柜号", bc.cy_open_at, MilestoneCode.CONTAINER_PICKED_UP),
        (TaskCode.SUBMIT_SI, "提交 SI 补料", si_cutoff, MilestoneCode.SI_SUBMITTED),
        (TaskCode.SUBMIT_VGM, "提交 VGM", vgm_cutoff, MilestoneCode.VGM_SUBMITTED),
    ]
    now = datetime.now(timezone.utc)
    for code, title, due_at, auto_close_on in new_tasks_specs:
        t = Task(
            organization_id=organization_id,
            shipment_id=shipment_id,
            code=code,
            title=title,
            due_at=due_at,
            auto_close_on=auto_close_on,
            status=TaskStatus.PENDING,
        )
        db.add(t)

    # 检查 schedule_changed (如果有旧 BC)
    other_bc = (await db.execute(
        select(BookingConfirmation).where(
            BookingConfirmation.shipment_id == shipment_id,
            BookingConfirmation.id != booking_confirmation_id,
            BookingConfirmation.is_current == False,  # noqa: E712
        )
    )).scalars().all()
    if other_bc:
        # 比对 ETD 变化
        old_etd = next((b.etd for b in other_bc if b.etd), None)
        if old_etd and bc.etd and old_etd != bc.etd:
            # 先关掉旧的 schedule_changed (避免"刚开就被自己关")
            await _auto_close_open_exceptions(
                db,
                organization_id=organization_id,
                shipment_id=shipment_id,
                codes=[ExceptionCode.SCHEDULE_CHANGED, ExceptionCode.PORT_CHANGED, ExceptionCode.CARRIER_CHANGED],
                resolution=f"auto closed: new confirmation accepted (new_etd={bc.etd.isoformat() if bc.etd else None})",
            )
            ex = OperationalException(
                organization_id=organization_id,
                shipment_id=shipment_id,
                code=ExceptionCode.SCHEDULE_CHANGED,
                severity=ExceptionSeverity.WARNING,
                status=ExceptionStatus.OPEN,
                detected_at=now,
                detected_by=ExceptionDetectedBy.SYSTEM,
                context={"old_etd": old_etd.isoformat(), "new_etd": bc.etd.isoformat()},
                related_milestone_id=ms.id,
            )
            db.add(ex)

    await db.commit()
    await db.refresh(ms)
    return ms


async def _auto_close_open_exceptions(
    db: AsyncSession,
    *,
    organization_id: str,
    shipment_id: str,
    codes: list[ExceptionCode],
    resolution: str,
) -> int:
    stmt = select(OperationalException).where(
        OperationalException.organization_id == organization_id,
        OperationalException.shipment_id == shipment_id,
        OperationalException.status == ExceptionStatus.OPEN,
        OperationalException.code.in_(codes),
    )
    opex_list = (await db.execute(stmt)).scalars().all()
    now = datetime.now(timezone.utc)
    for opex in opex_list:
        opex.status = ExceptionStatus.AUTO_CLOSED
        opex.resolved_at = now
        opex.resolution = resolution
    return len(opex_list)


# ========== BookingRequest sent 副作用 ==========


async def on_booking_request_sent(
    db: AsyncSession,
    *,
    organization_id: str,
    booking_request_id: str,
) -> Milestone:
    """BookingRequest /send 成功时: 创建 milestone + sla_hours 后开 overdue exception (后台任务, v0.5 暂不实现)"""
    br = (await db.execute(
        select(BookingRequest).where(BookingRequest.id == booking_request_id)
    )).scalar_one()
    ms = Milestone(
        organization_id=organization_id,
        shipment_id=br.shipment_id,
        code=MilestoneCode.BOOKING_REQUEST_SENT,
        occurred_at=br.sent_at or datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
        source=MilestoneSource.AUTO,
        source_ref=f"booking_request:{booking_request_id}",
    )
    db.add(ms)
    await db.commit()
    await db.refresh(ms)
    return ms


# ========== 异常自动 close (收新 SO 时) ==========


async def auto_close_exceptions_on_new_confirmation(
    db: AsyncSession,
    *,
    organization_id: str,
    shipment_id: str,
    new_etd=None,
) -> int:
    """收新 SO 时, 自动 close 相关异常 (schedule_changed / port_changed / carrier_changed).

    v0.5 简化: 只关 status=open 的. 返回关闭数量.
    """
    stmt = select(OperationalException).where(
        OperationalException.organization_id == organization_id,
        OperationalException.shipment_id == shipment_id,
        OperationalException.status == ExceptionStatus.OPEN,
        OperationalException.code.in_([
            ExceptionCode.SCHEDULE_CHANGED,
            ExceptionCode.PORT_CHANGED,
            ExceptionCode.CARRIER_CHANGED,
        ]),
    )
    opex_list = (await db.execute(stmt)).scalars().all()
    now = datetime.now(timezone.utc)
    for opex in opex_list:
        opex.status = ExceptionStatus.AUTO_CLOSED
        opex.resolved_at = now
        opex.resolution = f"auto closed: new SO accepted (etd={new_etd})"
    await db.commit()
    if opex_list:
        logger.info("auto_close {} exceptions for shipment {}", len(opex_list), shipment_id)
    return len(opex_list)
