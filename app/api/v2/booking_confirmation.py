"""BookingConfirmation API - v0.5 订舱确认 (SO 接受)"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction
from app.models.booking_confirmation import (
    BookingConfirmation,
    BookingConfirmationReviewStatus,
    BookingConfirmationStatus,
)
from app.models.shipment import Shipment, ShipmentStage
from app.schemas.booking_confirmation import (
    BookingConfirmationAccept,
    BookingConfirmationCreate,
    BookingConfirmationRead,
    BookingConfirmationReject,
)

router = APIRouter()

# P1#5 修复: overrides 字段白名单 (防 attacker 改 organization_id/shipment_id/version/id)
ALLOWED_OVERRIDE_FIELDS = frozenset({
    "carrier", "carrier_booking_no", "so_no", "bl_no",
    "vessel_name", "voyage_no", "pol", "pod",
    "etd", "eta", "cy_open_at", "si_cutoff_at",
    "vgm_cutoff_at", "cy_cutoff_at",
    "container_type", "container_count", "remark",
})


@router.post("/", response_model=BookingConfirmationRead, status_code=201)
async def create_booking_confirmation(
    payload: BookingConfirmationCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BookingConfirmationRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    # 验证 shipment
    s = (await db.execute(
        select(Shipment).where(Shipment.id == payload.shipment_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")

    # 自动 version: 同 shipment 最大 + 1
    from sqlalchemy import func
    stmt_max = select(func.max(BookingConfirmation.version)).where(
        BookingConfirmation.shipment_id == payload.shipment_id,
    )
    max_version = (await db.execute(stmt_max)).scalar_one() or 0
    new_version = max_version + 1

    # P1#4 修复: 避免双 is_current=true
    #   如果同 shipment 已有 ACCEPTED 的 current, 新建不设 current (留待审)
    #   否则按原来的"新版本默认 current"逻辑
    existing_accepted_current = (await db.execute(
        select(BookingConfirmation).where(
            BookingConfirmation.shipment_id == payload.shipment_id,
            BookingConfirmation.is_current == True,  # noqa: E712
            BookingConfirmation.status == BookingConfirmationStatus.ACCEPTED,
        )
    )).scalar_one_or_none()
    is_current = existing_accepted_current is None

    bc = BookingConfirmation(
        organization_id=org.id,
        shipment_id=payload.shipment_id,
        booking_request_id=payload.booking_request_id,
        document_id=payload.document_id,
        extraction_id=payload.extraction_id,
        carrier=payload.carrier,
        carrier_booking_no=payload.carrier_booking_no,
        so_no=payload.so_no,
        bl_no=payload.bl_no,
        vessel_name=payload.vessel_name,
        voyage_no=payload.voyage_no,
        pol=payload.pol,
        pod=payload.pod,
        etd=payload.etd,
        eta=payload.eta,
        cy_open_at=payload.cy_open_at,
        si_cutoff_at=payload.si_cutoff_at,
        vgm_cutoff_at=payload.vgm_cutoff_at,
        cy_cutoff_at=payload.cy_cutoff_at,
        container_type=payload.container_type,
        container_count=payload.container_count,
        context=payload.context,
        version=new_version,
        is_current=is_current,
        status=BookingConfirmationStatus.MATCHED_PENDING
        if s.id
        else BookingConfirmationStatus.UNMATCHED,
        review_status=BookingConfirmationReviewStatus.NEEDS_REVIEW,
        remark=payload.remark,
    )
    db.add(bc)
    await db.commit()
    await db.refresh(bc)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="booking_confirmation",
        entity_id=bc.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={
            "after": payload.model_dump(mode="json", exclude={"shipment_id"}),
            "version": new_version,
        },
    )
    await db.commit()
    return BookingConfirmationRead.model_validate(bc)


@router.get("/", response_model=list[BookingConfirmationRead])
async def list_booking_confirmations(
    shipment_id: str | None = Query(None),
    status: str | None = Query(None),
    is_current: bool | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[BookingConfirmationRead]:
    """'SO 收件箱': status=matched_pending + is_current=true 等"""
    org = await get_default_organization(db)
    stmt = select(BookingConfirmation).where(BookingConfirmation.organization_id == org.id)
    if shipment_id:
        stmt = stmt.where(BookingConfirmation.shipment_id == shipment_id)
    if status:
        try:
            status_enum = BookingConfirmationStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
        stmt = stmt.where(BookingConfirmation.status == status_enum)
    if is_current is not None:
        stmt = stmt.where(BookingConfirmation.is_current == is_current)
    stmt = stmt.order_by(BookingConfirmation.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [BookingConfirmationRead.model_validate(r) for r in rows]


@router.get("/{bc_id}", response_model=BookingConfirmationRead)
async def get_booking_confirmation(
    bc_id: str, db: AsyncSession = Depends(db_session)
) -> BookingConfirmationRead:
    bc = (await db.execute(
        select(BookingConfirmation).where(BookingConfirmation.id == bc_id)
    )).scalar_one_or_none()
    if not bc:
        raise HTTPException(status_code=404, detail="booking_confirmation not found")
    return BookingConfirmationRead.model_validate(bc)


@router.post("/{bc_id}/accept", response_model=BookingConfirmationRead)
async def accept_booking_confirmation(
    bc_id: str,
    payload: BookingConfirmationAccept,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BookingConfirmationRead:
    """接受 booking confirmation: 字段写入 Shipment, 旧 is_current 切到 false

    P1#4 修复: 旧 current BC 切到 false + 状态变 SUPERSEDED (避免双 current 500)
    P1#5 修复: overrides 字段白名单 (防改 organization_id / shipment_id / version / id)
    P1#6 修复: 原子事务 (BC 改 / Shipment 改 / workflow / audit 都在一个 try/except, 失败全 rollback)
    """
    bc = (await db.execute(
        select(BookingConfirmation).where(BookingConfirmation.id == bc_id)
    )).scalar_one_or_none()
    if not bc:
        raise HTTPException(status_code=404, detail="booking_confirmation not found")
    if bc.status in (
        BookingConfirmationStatus.ACCEPTED,
        BookingConfirmationStatus.REJECTED,
        BookingConfirmationStatus.SUPERSEDED,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"cannot accept with status={bc.status.value}",
        )
    actor = Actor.from_request(request)

    s = (await db.execute(
        select(Shipment).where(Shipment.id == bc.shipment_id)
    )).scalar_one()
    if s.stage.value == "cancelled":
        raise HTTPException(status_code=400, detail="cannot accept on cancelled shipment")

    # P1#5: overrides 字段白名单
    if payload.overrides:
        from datetime import date as _date
        for k, v in payload.overrides.items():
            if k not in ALLOWED_OVERRIDE_FIELDS:
                raise HTTPException(
                    status_code=400,
                    detail=f"override field not allowed: {k!r} (allowed: {sorted(ALLOWED_OVERRIDE_FIELDS)})",
                )
            if not hasattr(bc, k):
                raise HTTPException(status_code=400, detail=f"unknown field: {k}")
            # 日期/时间字段: str → date/datetime (前端可能传 ISO str)
            current_val = getattr(bc.__class__, k, None)
            if v is not None and current_val is not None and not isinstance(v, (str, int, float, bool)):
                # 非原生类型, 跳过
                pass
            # 简单的 ISO 字符串 → date 转换
            if k in ("etd", "eta") and isinstance(v, str):
                try:
                    v = _date.fromisoformat(v)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"override {k} must be ISO date (YYYY-MM-DD), got: {v!r}",
                    )
            elif k in ("cy_open_at", "si_cutoff_at", "vgm_cutoff_at", "cy_cutoff_at") and isinstance(v, str):
                from datetime import datetime as _dt
                try:
                    v = _dt.fromisoformat(v.replace("Z", "+00:00"))
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"override {k} must be ISO datetime, got: {v!r}",
                    )
            setattr(bc, k, v)

    # P1#6: 原子事务 - 所有改动在一个 try/except, 失败全 rollback
    try:
        # 旧 is_current 切到 false (P1#4 修复: 避免双 current 引起 500)
        stmt_others = select(BookingConfirmation).where(
            BookingConfirmation.shipment_id == bc.shipment_id,
            BookingConfirmation.id != bc.id,
            BookingConfirmation.is_current == True,  # noqa: E712
        )
        others = (await db.execute(stmt_others)).scalars().all()
        for o in others:
            o.is_current = False
            if o.status != BookingConfirmationStatus.REJECTED:
                o.status = BookingConfirmationStatus.SUPERSEDED
            o.supersedes_id = bc.id

        # 切本条为 accepted
        bc.status = BookingConfirmationStatus.ACCEPTED
        bc.is_current = True
        bc.review_status = BookingConfirmationReviewStatus.REVIEWED
        bc.accepted_at = datetime.now(timezone.utc)
        bc.accepted_by = actor.actor_user_id
        bc.accepted_by_name = actor.actor_user_name

        # 字段写入 Shipment
        s.carrier_booking_no = bc.carrier_booking_no or s.carrier_booking_no
        s.so_no = bc.so_no or s.so_no
        s.bl_no = bc.bl_no or s.bl_no
        s.etd = bc.etd or s.etd
        s.eta = bc.eta or s.eta
        s.current_carrier = bc.carrier or s.current_carrier
        # 简单 stage 推进: draft / booking_in_progress / awaiting_confirmation → booked
        if s.stage in (
            ShipmentStage.DRAFT,
            ShipmentStage.BOOKING_IN_PROGRESS,
            ShipmentStage.AWAITING_CONFIRMATION,
        ):
            s.stage = ShipmentStage.BOOKED

        # workflow: 创建 milestone + 关 task + 开新 task + 自动 close 旧异常
        from app.services.workflow import on_booking_confirmation_accepted
        await on_booking_confirmation_accepted(
            db,
            organization_id=bc.organization_id,
            shipment_id=bc.shipment_id,
            booking_confirmation_id=bc.id,
        )

        # 一次 commit 全部事务 (P1#6 原子)
        await db.commit()
        await db.refresh(bc)
        await db.refresh(s)
    except Exception as e:
        await db.rollback()
        # 写一条失败 audit 留痕 (独立 commit)
        try:
            await write_audit_log(
                db,
                organization_id=bc.organization_id,
                entity_type="booking_confirmation",
                entity_id=bc.id,
                action=AuditAction.ACCEPT,
                actor=actor,
                field_changes={"error": str(e)[:200], "rolled_back": True},
                reason=f"accept failed and rolled back: {e}",
            )
            await db.commit()
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"accept booking_confirmation failed, all changes rolled back: {e}",
        )

    # audit (独立, 失败不影响主事务)
    try:
        await write_audit_log(
            db,
            organization_id=bc.organization_id,
            entity_type="booking_confirmation",
            entity_id=bc.id,
            action=AuditAction.ACCEPT,
            actor=actor,
            field_changes={
                "version": bc.version,
                "carrier_booking_no": bc.carrier_booking_no,
                "etd": bc.etd.isoformat() if bc.etd else None,
            },
            reason=payload.reason,
        )
        # 同步 shippment 字段改动 audit
        await write_audit_log(
            db,
            organization_id=s.organization_id,
            entity_type="shipment",
            entity_id=s.id,
            action=AuditAction.UPDATE,
            actor=actor,
            field_changes={
                "etd": {"old": None, "new": bc.etd.isoformat() if bc.etd else None},
                "carrier_booking_no": {"old": None, "new": bc.carrier_booking_no},
                "stage": {"old": "draft_or_pending", "new": "booked"},
            },
            reason=f"accepted booking_confirmation {bc.id}",
        )
        await db.commit()
    except Exception:
        # audit 失败不阻断
        await db.rollback()

    return BookingConfirmationRead.model_validate(bc)


@router.post("/{bc_id}/reject", response_model=BookingConfirmationRead)
async def reject_booking_confirmation(
    bc_id: str,
    payload: BookingConfirmationReject,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BookingConfirmationRead:
    bc = (await db.execute(
        select(BookingConfirmation).where(BookingConfirmation.id == bc_id)
    )).scalar_one_or_none()
    if not bc:
        raise HTTPException(status_code=404, detail="booking_confirmation not found")
    actor = Actor.from_request(request)

    bc.status = BookingConfirmationStatus.REJECTED
    bc.is_current = False
    await db.commit()
    await db.refresh(bc)

    await write_audit_log(
        db,
        organization_id=bc.organization_id,
        entity_type="booking_confirmation",
        entity_id=bc.id,
        action=AuditAction.REJECT,
        actor=actor,
        reason=payload.reason,
    )
    await db.commit()
    return BookingConfirmationRead.model_validate(bc)
