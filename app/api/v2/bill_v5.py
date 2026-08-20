"""Bill v0.5 API"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction
from app.models.bill_v5 import (
    BILL_TRANSITIONS, BillKind, BillStatus, BillType, BillV5,
)
from app.models.shipment import Shipment
from app.schemas.bill_v5 import (
    BillStatusTransition,
    BillV5Create,
    BillV5Read,
    BillV5Update,
)

router = APIRouter()


@router.post("/", response_model=BillV5Read, status_code=201)
async def create_bill(
    payload: BillV5Create,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BillV5Read:
    """新建 Bill (v0.5)"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    # 验证 shipment_id
    if payload.shipment_id:
        ship = (await db.execute(
            select(Shipment).where(Shipment.id == payload.shipment_id)
        )).scalar_one_or_none()
        if not ship:
            raise HTTPException(status_code=400, detail="shipment not found")

    bill = BillV5(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        bill_no=payload.bill_no,
        bill_type=BillType(payload.bill_type),
        bill_kind=BillKind(payload.bill_kind),
        shipment_id=payload.shipment_id,
        seller_name=payload.seller_name,
        buyer_name=payload.buyer_name,
        currency=payload.currency,
        total_amount=payload.total_amount,
        tax_amount=payload.tax_amount,
        amount_excl_tax=payload.amount_excl_tax,
        due_at=payload.due_at,
        remark=payload.remark,
        status=BillStatus.UPLOADED,
    )
    db.add(bill)
    await db.commit()
    await db.refresh(bill)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="bill",
        entity_id=bill.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={"after": {"bill_no": bill.bill_no, "amount": bill.total_amount}},
    )
    await db.commit()
    return BillV5Read.model_validate(bill)


@router.get("/", response_model=list[BillV5Read])
async def list_bills(
    shipment_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[BillV5Read]:
    org = await get_default_organization(db)
    stmt = select(BillV5).where(BillV5.organization_id == org.id)
    if shipment_id:
        stmt = stmt.where(BillV5.shipment_id == shipment_id)
    if status:
        try:
            stmt = stmt.where(BillV5.status == BillStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
    stmt = stmt.order_by(BillV5.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [BillV5Read.model_validate(r) for r in rows]


@router.get("/{bill_id}", response_model=BillV5Read)
async def get_bill(
    bill_id: str, db: AsyncSession = Depends(db_session)
) -> BillV5Read:
    bill = (await db.execute(
        select(BillV5).where(BillV5.id == bill_id)
    )).scalar_one_or_none()
    if not bill:
        raise HTTPException(status_code=404, detail="bill not found")
    return BillV5Read.model_validate(bill)


@router.patch("/{bill_id}", response_model=BillV5Read)
async def update_bill(
    bill_id: str,
    payload: BillV5Update,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BillV5Read:
    bill = (await db.execute(
        select(BillV5).where(BillV5.id == bill_id)
    )).scalar_one_or_none()
    if not bill:
        raise HTTPException(status_code=404, detail="bill not found")
    if bill.status == BillStatus.PAID:
        raise HTTPException(status_code=400, detail="paid bill is terminal")
    actor = Actor.from_request(request)

    before = {k: getattr(bill, k) for k in payload.model_fields_set}

    for k, v in payload.model_dump(exclude_unset=True).items():
        if k in ("bill_type", "bill_kind"):
            setattr(bill, k, type(getattr(bill, k))(v))
        else:
            setattr(bill, k, v)

    await db.commit()
    await db.refresh(bill)

    after = {k: getattr(bill, k) for k in payload.model_fields_set}
    field_changes = {}
    for k in after:
        old_v = before.get(k)
        new_v = after.get(k)
        if hasattr(old_v, "isoformat"):
            old_v = old_v.isoformat()
        if hasattr(new_v, "isoformat"):
            new_v = new_v.isoformat()
        if old_v != new_v:
            field_changes[k] = {"old": old_v, "new": new_v}
    if field_changes:
        await write_audit_log(
            db,
            organization_id=bill.organization_id,
            entity_type="bill",
            entity_id=bill.id,
            action=AuditAction.UPDATE,
            actor=actor,
            field_changes=field_changes,
        )
        await db.commit()
    return BillV5Read.model_validate(bill)


@router.post("/{bill_id}/transition", response_model=BillV5Read)
async def transition_bill(
    bill_id: str,
    payload: BillStatusTransition,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BillV5Read:
    """Bill 状态机 transition

    合法转换 (见 BILL_TRANSITIONS):
    - uploaded → ocr_processing/ocr_failed/confirmed
    - ocr_processing → ocr_done/ocr_failed
    - ocr_done → confirmed/disputed/ocr_processing
    - ocr_failed → ocr_processing/uploaded
    - confirmed → paid/disputed
    - disputed → confirmed/paid
    - paid: 终态
    """
    bill = (await db.execute(
        select(BillV5).where(BillV5.id == bill_id)
    )).scalar_one_or_none()
    if not bill:
        raise HTTPException(status_code=404, detail="bill not found")
    actor = Actor.from_request(request)

    try:
        target = BillStatus(payload.to)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid status: {payload.to}")

    current = bill.status
    allowed = BILL_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"invalid transition: {current.value} → {target.value}. "
                   f"allowed: {[s.value for s in allowed]}",
        )

    old_status = current.value
    bill.status = target
    if target == BillStatus.PAID:
        bill.paid_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(bill)

    await write_audit_log(
        db,
        organization_id=bill.organization_id,
        entity_type="bill",
        entity_id=bill.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes={"status": {"old": old_status, "new": target.value}},
        reason=payload.reason,
    )
    await db.commit()
    return BillV5Read.model_validate(bill)
