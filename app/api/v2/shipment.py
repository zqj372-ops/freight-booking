"""Shipment API - v0.5 业务主对象"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction
from app.models.booking_request import BookingRequest, BookingRequestStatus
from app.models.container import Container
from app.models.partner import Partner
from app.models.shipment import Shipment, ShipmentStage
from app.schemas.shipment import (
    ShipmentCreate,
    ShipmentListQuery,
    ShipmentRead,
    ShipmentStageChange,
    ShipmentUpdate,
)
from app.services.numbering import generate_job_no

router = APIRouter()


@router.post("/", response_model=ShipmentRead, status_code=201)
async def create_shipment(
    payload: ShipmentCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ShipmentRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    job_no = await generate_job_no(db, org)

    # 验证 customer_partner_id 存在
    if payload.customer_partner_id:
        cp = (await db.execute(
            select(Partner).where(Partner.id == payload.customer_partner_id)
        )).scalar_one_or_none()
        if not cp:
            raise HTTPException(status_code=400, detail="customer_partner not found")
        if cp.partner_type.value != "customer":
            raise HTTPException(
                status_code=400,
                detail=f"partner {cp.id} is type={cp.partner_type.value}, not customer",
            )

    # 验证 current_partner_id 存在
    if payload.current_partner_id:
        pp = (await db.execute(
            select(Partner).where(Partner.id == payload.current_partner_id)
        )).scalar_one_or_none()
        if not pp:
            raise HTTPException(status_code=400, detail="current_partner not found")

    s = Shipment(
        organization_id=org.id,
        job_no=job_no,
        **payload.model_dump(),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)

    # 自动建 1 个 TBD Container
    container = Container(
        organization_id=org.id,
        shipment_id=s.id,
        container_type="40HQ",  # v0.5 默认, 后续 v0.6 接受 SO 后从 BC 覆盖
    )
    db.add(container)
    await db.commit()

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="shipment",
        entity_id=s.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={"after": {"job_no": s.job_no, **payload.model_dump(mode="json")}},
    )
    await db.commit()
    return ShipmentRead.model_validate(s)


@router.get("/", response_model=list[ShipmentRead])
async def list_shipments(
    stage: str | None = Query(None),
    customer_partner_id: str | None = None,
    current_partner_id: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    search: str | None = Query(None, description="job_no/customer_ref/legacy_job_no 模糊"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[ShipmentRead]:
    org = await get_default_organization(db)
    stmt = select(Shipment).where(Shipment.organization_id == org.id)
    if stage:
        try:
            stage_enum = ShipmentStage(stage)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid stage: {stage}")
        stmt = stmt.where(Shipment.stage == stage_enum)
    if customer_partner_id:
        stmt = stmt.where(Shipment.customer_partner_id == customer_partner_id)
    if current_partner_id:
        stmt = stmt.where(Shipment.current_partner_id == current_partner_id)
    if pol:
        stmt = stmt.where(Shipment.pol == pol)
    if pod:
        stmt = stmt.where(Shipment.pod == pod)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (Shipment.job_no.like(like))
            | (Shipment.customer_ref.like(like))
            | (Shipment.legacy_job_no.like(like))
        )
    stmt = stmt.order_by(Shipment.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [ShipmentRead.model_validate(r) for r in rows]


@router.get("/{shipment_id}", response_model=ShipmentRead)
async def get_shipment(
    shipment_id: str, db: AsyncSession = Depends(db_session)
) -> ShipmentRead:
    s = (await db.execute(
        select(Shipment).where(Shipment.id == shipment_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")
    return ShipmentRead.model_validate(s)


@router.get("/by-job-no/{job_no}", response_model=ShipmentRead)
async def get_shipment_by_job_no(
    job_no: str, db: AsyncSession = Depends(db_session)
) -> ShipmentRead:
    """通过业务编号查 (UI 详情页常用)"""
    s = (await db.execute(
        select(Shipment).where(Shipment.job_no == job_no)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")
    return ShipmentRead.model_validate(s)


@router.patch("/{shipment_id}", response_model=ShipmentRead)
async def update_shipment(
    shipment_id: str,
    payload: ShipmentUpdate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ShipmentRead:
    s = (await db.execute(
        select(Shipment).where(Shipment.id == shipment_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")
    if s.stage == ShipmentStage.CANCELLED:
        raise HTTPException(status_code=400, detail="cancelled shipment is terminal, cannot update")
    actor = Actor.from_request(request)

    before = {k: getattr(s, k) for k in payload.model_fields_set}
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    await db.commit()
    await db.refresh(s)

    after = {k: getattr(s, k) for k in payload.model_fields_set}
    field_changes = {k: {"old": before.get(k), "new": after.get(k)} for k in payload.model_fields_set}
    await write_audit_log(
        db,
        organization_id=s.organization_id,
        entity_type="shipment",
        entity_id=s.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes=field_changes,
    )
    await db.commit()
    return ShipmentRead.model_validate(s)


@router.post("/{shipment_id}/stage", response_model=ShipmentRead)
async def change_stage(
    shipment_id: str,
    payload: ShipmentStageChange,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ShipmentRead:
    """手动调整 stage (留 audit log + reason 必填)"""
    s = (await db.execute(
        select(Shipment).where(Shipment.id == shipment_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")
    actor = Actor.from_request(request)

    old_stage = s.stage
    new_stage = ShipmentStage(payload.stage)
    s.stage = new_stage
    if new_stage == ShipmentStage.CANCELLED:
        s.cancelled_at = datetime.now(timezone.utc)
        s.cancellation_reason = payload.reason
    if new_stage == ShipmentStage.COMPLETED:
        s.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)

    await write_audit_log(
        db,
        organization_id=s.organization_id,
        entity_type="shipment",
        entity_id=s.id,
        action=AuditAction.STAGE_CHANGE,
        actor=actor,
        field_changes={"stage": {"old": old_stage.value, "new": new_stage.value}},
        reason=payload.reason,
    )
    await db.commit()
    return ShipmentRead.model_validate(s)


@router.get("/{shipment_id}/booking-requests", response_model=list)
async def list_shipment_booking_requests(
    shipment_id: str, db: AsyncSession = Depends(db_session)
) -> list:
    """业务详情页 "订舱申请" tab"""
    from app.schemas.booking_request import BookingRequestRead

    stmt = (
        select(BookingRequest)
        .where(BookingRequest.shipment_id == shipment_id)
        .order_by(BookingRequest.request_version.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [BookingRequestRead.model_validate(r) for r in rows]


@router.get("/{shipment_id}/booking-confirmations", response_model=list)
async def list_shipment_booking_confirmations(
    shipment_id: str, db: AsyncSession = Depends(db_session)
) -> list:
    """业务详情页 "SO 确认" tab"""
    from app.models.booking_confirmation import BookingConfirmation
    from app.schemas.booking_confirmation import BookingConfirmationRead

    stmt = (
        select(BookingConfirmation)
        .where(BookingConfirmation.shipment_id == shipment_id)
        .order_by(BookingConfirmation.version.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [BookingConfirmationRead.model_validate(r) for r in rows]


@router.get("/{shipment_id}/containers", response_model=list)
async def list_shipment_containers(
    shipment_id: str, db: AsyncSession = Depends(db_session)
) -> list:
    """业务详情页 "柜" tab"""
    from app.schemas.container import ContainerRead

    stmt = select(Container).where(Container.shipment_id == shipment_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [ContainerRead.model_validate(r) for r in rows]
