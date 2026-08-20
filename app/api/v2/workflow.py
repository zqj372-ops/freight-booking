"""Milestone + Task + OperationalException API - v0.5"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction, BusinessPhase, PHASE_LABELS
from app.models.operational_exception import (
    ExceptionDetectedBy,
    ExceptionSeverity,
    ExceptionStatus,
)
from app.models.task import TaskStatus
from app.models.booking_request import BookingRequest, BookingRequestStatus
from app.models.booking_confirmation import BookingConfirmation
from app.models.milestone import Milestone
from app.models.operational_exception import OperationalException
from app.models.shipment import Shipment, ShipmentStage
from app.models.task import Task
from app.schemas.milestone import (
    MilestoneCreate,
    MilestoneRead,
    OpExCreate,
    OpExRead,
    OpExResolve,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)
from app.services.workflow import (
    auto_close_exceptions_on_new_confirmation,
    auto_close_tasks_for_milestone,
    derive_business_phase,
    derive_phase_color,
    derive_phase_progress,
    derive_stage,
    on_booking_confirmation_accepted,
    on_booking_request_sent,
)

router = APIRouter()


# ========== Milestone ==========


@router.post("/shipments/{shipment_id}/milestones", response_model=MilestoneRead, status_code=201)
async def create_milestone(
    shipment_id: str,
    payload: MilestoneCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> MilestoneRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    s = (await db.execute(
        select(Shipment).where(
            Shipment.id == shipment_id,
            Shipment.organization_id == org.id,
        )
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")
    # P1#7 修复: cancelled 终态, 不允许加业务事实
    if s.stage == ShipmentStage.CANCELLED:
        raise HTTPException(
            status_code=400,
            detail="cancelled shipment is terminal, cannot add milestones (create new Shipment instead)",
        )

    now = datetime.now(timezone.utc)
    ms = Milestone(
        organization_id=org.id,
        shipment_id=shipment_id,
        code=payload.code,
        occurred_at=payload.occurred_at,
        recorded_at=now,
        source=payload.source,
        source_ref=payload.source_ref,
        location=payload.location,
        vessel_name=payload.vessel_name,
        voyage_no=payload.voyage_no,
        container_no=payload.container_no,
        remark=payload.remark,
    )
    db.add(ms)
    await db.flush()

    # 自动 close 对应 task
    from app.models.milestone import MilestoneCode
    closed_tasks = await auto_close_tasks_for_milestone(
        db,
        organization_id=org.id,
        shipment_id=shipment_id,
        milestone_code=MilestoneCode(payload.code),
    )

    # 关键 milestone 触发 SLA trigger (e.g. departed → get_onboard_bl / get_emf)
    _MILESTONE_TO_TRIGGER = {
        "departed": "departed",
        "container_picked_up": None,  # 暂无 trigger
        "container_loaded": None,
        "si_submitted": None,  # si_sent 触发是 si_info_ready_at
        "vgm_submitted": None,
        "customs_cleared": "customs_released",
        "arrived_at_pod": None,
    }
    from app.services.triggers import fire_event, TriggerEvent
    trigger_name = _MILESTONE_TO_TRIGGER.get(payload.code)
    if trigger_name:
        try:
            await fire_event(
                db, event=TriggerEvent(trigger_name),
                shipment=s, occurred_at=payload.occurred_at,
            )
        except (ValueError, KeyError):
            pass  # 未注册的 trigger 跳过

    await db.commit()
    await db.refresh(ms)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="milestone",
        entity_id=ms.id,
        action=AuditAction.RECORD,
        actor=actor,
        field_changes={
            "after": {"code": payload.code, "occurred_at": payload.occurred_at.isoformat()},
            "auto_closed_tasks": [t.id for t in closed_tasks],
        },
    )
    await db.commit()
    return MilestoneRead.model_validate(ms)


@router.get("/shipments/{shipment_id}/milestones", response_model=list[MilestoneRead])
async def list_milestones(
    shipment_id: str, db: AsyncSession = Depends(db_session)
) -> list[MilestoneRead]:
    stmt = (
        select(Milestone)
        .where(Milestone.shipment_id == shipment_id)
        .order_by(Milestone.occurred_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [MilestoneRead.model_validate(r) for r in rows]


@router.get("/shipments/{shipment_id}/derived-stage", response_model=dict)
async def get_derived_stage(
    shipment_id: str, db: AsyncSession = Depends(db_session)
) -> dict:
    """由 Milestone 集合推导 Shipment.stage (软联动)"""
    stmt = select(Milestone).where(Milestone.shipment_id == shipment_id)
    ms = (await db.execute(stmt)).scalars().all()
    stage = derive_stage(ms)
    return {
        "shipment_id": shipment_id,
        "derived_stage": stage.value,
        "milestone_count": len(ms),
    }


# v0.5 1.5: 8 业务阶段 + 颜色 + 进度 (UI 主列表和详情页进度条用)
@router.get("/shipments/{shipment_id}/business-phase", response_model=dict)
async def get_business_phase(
    shipment_id: str, db: AsyncSession = Depends(db_session)
) -> dict:
    """v0.5 1.5: 8 业务阶段 (1-8) + 颜色 + 进度.

    前端 React 主列表 / 详情页进度条直接调这个 endpoint.
    """
    stmt = select(Milestone).where(Milestone.shipment_id == shipment_id)
    ms = (await db.execute(stmt)).scalars().all()
    phase = derive_business_phase(ms)

    # 查最近 open exception 决定颜色
    ex_stmt = select(OperationalException).where(
        OperationalException.shipment_id == shipment_id,
        OperationalException.status == ExceptionStatus.OPEN,
    )
    has_open_ex = (await db.execute(ex_stmt)).scalars().first() is not None

    # 找最近 due task
    from app.models.task import Task
    task_stmt = select(Task).where(
        Task.shipment_id == shipment_id,
        Task.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
    ).order_by(Task.due_at.asc().nulls_last())
    next_task = (await db.execute(task_stmt)).scalars().first()
    next_due = next_task.due_at if next_task else None

    color = derive_phase_color(phase, next_due, has_open_ex)
    progress = derive_phase_progress(ms)

    return {
        "shipment_id": shipment_id,
        "phase": phase.value,
        "phase_label": PHASE_LABELS.get(phase.value, ""),
        "color": color.value,
        "progress": progress,
        "milestone_count": len(ms),
        "has_open_exception": has_open_ex,
        "next_due_at": next_due.isoformat() if next_due else None,
        "next_task_title": next_task.title if next_task else None,
    }


# ========== Task ==========


@router.post("/shipments/{shipment_id}/tasks", response_model=TaskRead, status_code=201)
async def create_task(
    shipment_id: str,
    payload: TaskCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> TaskRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    s = (await db.execute(
        select(Shipment).where(
            Shipment.id == shipment_id,
            Shipment.organization_id == org.id,
        )
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")
    # P1#7 修复: cancelled 终态, 不允许加 task
    if s.stage == ShipmentStage.CANCELLED:
        raise HTTPException(
            status_code=400,
            detail="cancelled shipment is terminal, cannot add tasks (create new Shipment instead)",
        )

    t = Task(
        organization_id=org.id,
        shipment_id=shipment_id,
        code=payload.code,
        title=payload.title,
        description=payload.description,
        due_at=payload.due_at,
        assignee_user_id=payload.assignee_user_id,
        assignee_user_name=payload.assignee_user_name,
        auto_close_on=payload.auto_close_on,
        context=payload.context,
        status=TaskStatus.PENDING,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="task",
        entity_id=t.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={"after": payload.model_dump(mode="json")},
    )
    await db.commit()
    return TaskRead.model_validate(t)


@router.get("/shipments/{shipment_id}/tasks", response_model=list[TaskRead])
async def list_tasks(
    shipment_id: str,
    status: str | None = Query(None),
    db: AsyncSession = Depends(db_session),
) -> list[TaskRead]:
    stmt = select(Task).where(Task.shipment_id == shipment_id)
    if status:
        stmt = stmt.where(Task.status == status)
    stmt = stmt.order_by(Task.due_at.asc().nulls_last(), Task.created_at.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return [TaskRead.model_validate(r) for r in rows]


@router.patch("/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> TaskRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    t = (await db.execute(
        select(Task).where(
            Task.id == task_id,
            Task.organization_id == org.id,
        )
    )).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="task not found")

    before = {k: getattr(t, k) for k in payload.model_fields_set}
    new_status = payload.status
    old_status = t.status

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(t, k, v)

    if new_status == TaskStatus.DONE and old_status != TaskStatus.DONE:
        t.completed_at = datetime.now(timezone.utc)
        t.completed_by = actor.actor_user_id
        t.completed_by_name = actor.actor_user_name

    await db.commit()
    await db.refresh(t)

    after = {k: getattr(t, k) for k in payload.model_fields_set}
    field_changes = {k: {"old": before.get(k), "new": after.get(k)} for k in payload.model_fields_set}
    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="task",
        entity_id=t.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes=field_changes,
    )
    await db.commit()
    return TaskRead.model_validate(t)


# ========== OperationalException ==========


@router.post("/shipments/{shipment_id}/exceptions", response_model=OpExRead, status_code=201)
async def create_exception(
    shipment_id: str,
    payload: OpExCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> OpExRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    s = (await db.execute(
        select(Shipment).where(
            Shipment.id == shipment_id,
            Shipment.organization_id == org.id,
        )
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")
    # P1#7 修复: cancelled 终态, 不允许加 exception
    if s.stage == ShipmentStage.CANCELLED:
        raise HTTPException(
            status_code=400,
            detail="cancelled shipment is terminal, cannot add exceptions (create new Shipment instead)",
        )

    from app.models.operational_exception import ExceptionDetectedBy, ExceptionSeverity
    ex = OperationalException(
        organization_id=org.id,
        shipment_id=shipment_id,
        code=payload.code,
        severity=ExceptionSeverity(payload.severity),
        status=ExceptionStatus.OPEN,
        detected_at=datetime.now(timezone.utc),
        detected_by=ExceptionDetectedBy.MANUAL,
        context=payload.context,
        related_milestone_id=payload.related_milestone_id,
        related_task_id=payload.related_task_id,
    )
    db.add(ex)
    await db.commit()
    await db.refresh(ex)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="operational_exception",
        entity_id=ex.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes={"after": payload.model_dump(mode="json")},
    )
    await db.commit()
    return OpExRead.model_validate(ex)


@router.get("/shipments/{shipment_id}/exceptions", response_model=list[OpExRead])
async def list_exceptions(
    shipment_id: str,
    status: str | None = Query(None),
    db: AsyncSession = Depends(db_session),
) -> list[OpExRead]:
    stmt = select(OperationalException).where(OperationalException.shipment_id == shipment_id)
    if status:
        stmt = stmt.where(OperationalException.status == status)
    stmt = stmt.order_by(OperationalException.detected_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [OpExRead.model_validate(r) for r in rows]


@router.post("/exceptions/{ex_id}/resolve", response_model=OpExRead)
async def resolve_exception(
    ex_id: str,
    payload: OpExResolve,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> OpExRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    ex = (await db.execute(
        select(OperationalException).where(
            OperationalException.id == ex_id,
            OperationalException.organization_id == org.id,
        )
    )).scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="exception not found")
    if ex.status != ExceptionStatus.OPEN:
        raise HTTPException(status_code=400, detail=f"exception is {ex.status.value}")

    ex.status = ExceptionStatus.RESOLVED
    ex.resolved_at = datetime.now(timezone.utc)
    ex.resolved_by = actor.actor_user_id
    ex.resolved_by_name = actor.actor_user_name
    ex.resolution = payload.resolution
    await db.commit()
    await db.refresh(ex)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="operational_exception",
        entity_id=ex.id,
        action=AuditAction.RESOLVE,
        actor=actor,
        reason=payload.resolution,
    )
    await db.commit()
    return OpExRead.model_validate(ex)
