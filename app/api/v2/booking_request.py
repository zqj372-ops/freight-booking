"""BookingRequest API - v0.5 订舱申请"""

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
from app.models.partner import Partner
from app.models.shipment import Shipment
from app.schemas.booking_request import (
    BookingRequestCancel,
    BookingRequestCreate,
    BookingRequestRead,
    BookingRequestSend,
    BookingRequestUpdate,
)
from app.services.numbering import build_cargo_snapshot, generate_booking_request_no

router = APIRouter()


@router.post("/", response_model=BookingRequestRead, status_code=201)
async def create_booking_request(
    payload: BookingRequestCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BookingRequestRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    # 验证 shipment
    s = (await db.execute(
        select(Shipment).where(Shipment.id == payload.shipment_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")
    if s.stage.value == "cancelled":
        raise HTTPException(
            status_code=400, detail="cannot add booking_request to cancelled shipment"
        )

    # 验证 partner
    p = (await db.execute(
        select(Partner).where(Partner.id == payload.partner_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="partner not found")
    if p.partner_type.value not in ("agent_l1", "agent_l2", "carrier"):
        raise HTTPException(
            status_code=400,
            detail=f"partner must be agent_l1/l2/carrier, got {p.partner_type.value}",
        )

    # 处理 supersedes_id
    request_version = 1
    if payload.supersedes_id:
        old = (await db.execute(
            select(BookingRequest).where(BookingRequest.id == payload.supersedes_id)
        )).scalar_one_or_none()
        if not old:
            raise HTTPException(status_code=404, detail="supersedes target not found")
        if old.shipment_id != payload.shipment_id:
            raise HTTPException(
                status_code=400,
                detail="supersedes target belongs to different shipment",
            )
        request_version = old.request_version + 1
        # 旧版本不动, supersedes_id 留给 UI 反向查

    # 编号
    booking_request_no = await generate_booking_request_no(db, payload.shipment_id)

    # cargo_snapshot
    snapshot = build_cargo_snapshot(
        pol=payload.requested_pol,
        pod=payload.requested_pod,
        target_etd=payload.requested_etd,
        commodity=s.commodity,
        container_type=payload.requested_container_type,
        container_count=payload.requested_container_count,
        customer_ref=s.customer_ref,
        pieces=s.pieces,
        weight_kg=s.weight_kg,
        volume_cbm=s.volume_cbm,
        is_dangerous=s.is_dangerous,
        is_oversize=s.is_oversize,
        hs_code=s.hs_code,
        remark=s.remark,
        final_destination=s.final_destination,
    )

    br = BookingRequest(
        organization_id=org.id,
        shipment_id=payload.shipment_id,
        partner_id=payload.partner_id,
        booking_request_no=booking_request_no,
        request_version=request_version,
        supersedes_id=payload.supersedes_id,
        cargo_snapshot=snapshot,
        requested_etd=payload.requested_etd,
        requested_pol=payload.requested_pol,
        requested_pod=payload.requested_pod,
        requested_container_type=payload.requested_container_type,
        requested_container_count=payload.requested_container_count,
        carrier_preference=payload.carrier_preference,
        status=BookingRequestStatus.DRAFT,
        expected_response_by=payload.expected_response_by,
        response_sla_hours=payload.response_sla_hours or p.response_sla_hours,
        remark=payload.remark,
    )
    db.add(br)
    await db.commit()
    await db.refresh(br)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="booking_request",
        entity_id=br.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={"after": payload.model_dump(mode="json", exclude={"shipment_id"})},
    )
    await db.commit()
    return BookingRequestRead.model_validate(br)


@router.get("/", response_model=list[BookingRequestRead])
async def list_booking_requests(
    shipment_id: str | None = Query(None),
    partner_id: str | None = None,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[BookingRequestRead]:
    org = await get_default_organization(db)
    stmt = select(BookingRequest).where(BookingRequest.organization_id == org.id)
    if shipment_id:
        stmt = stmt.where(BookingRequest.shipment_id == shipment_id)
    if partner_id:
        stmt = stmt.where(BookingRequest.partner_id == partner_id)
    if status:
        try:
            status_enum = BookingRequestStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
        stmt = stmt.where(BookingRequest.status == status_enum)
    stmt = stmt.order_by(BookingRequest.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [BookingRequestRead.model_validate(r) for r in rows]


@router.get("/{br_id}", response_model=BookingRequestRead)
async def get_booking_request(
    br_id: str, db: AsyncSession = Depends(db_session)
) -> BookingRequestRead:
    br = (await db.execute(
        select(BookingRequest).where(BookingRequest.id == br_id)
    )).scalar_one_or_none()
    if not br:
        raise HTTPException(status_code=404, detail="booking_request not found")
    return BookingRequestRead.model_validate(br)


@router.patch("/{br_id}", response_model=BookingRequestRead)
async def update_booking_request(
    br_id: str,
    payload: BookingRequestUpdate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BookingRequestRead:
    br = (await db.execute(
        select(BookingRequest).where(BookingRequest.id == br_id)
    )).scalar_one_or_none()
    if not br:
        raise HTTPException(status_code=404, detail="booking_request not found")
    if br.status != BookingRequestStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail=f"can only update DRAFT booking_request, current status={br.status.value}",
        )
    actor = Actor.from_request(request)

    before = {k: getattr(br, k) for k in payload.model_fields_set}
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(br, k, v)
    await db.commit()
    await db.refresh(br)

    after = {k: getattr(br, k) for k in payload.model_fields_set}
    field_changes = {k: {"old": before.get(k), "new": after.get(k)} for k in payload.model_fields_set}
    await write_audit_log(
        db,
        organization_id=br.organization_id,
        entity_type="booking_request",
        entity_id=br.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes=field_changes,
    )
    await db.commit()
    return BookingRequestRead.model_validate(br)


@router.post("/{br_id}/send", response_model=BookingRequestRead)
async def send_booking_request(
    br_id: str,
    payload: BookingRequestSend,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BookingRequestRead:
    """发送订舱申请.

    v0.5 简化: dry_run 模式只渲染不发, 真实 send 复用 v0.4 email_service.
    邮件主题自动加 [job_no] 前缀.
    """
    from app.models.email_log import EmailLog, EmailStatus
    from app.services.email_service import render_template
    from app.models.email_template import EmailTemplate

    br = (await db.execute(
        select(BookingRequest).where(BookingRequest.id == br_id)
    )).scalar_one_or_none()
    if not br:
        raise HTTPException(status_code=404, detail="booking_request not found")
    if br.status not in (BookingRequestStatus.DRAFT, BookingRequestStatus.ACKNOWLEDGED):
        raise HTTPException(
            status_code=400,
            detail=f"cannot send booking_request with status={br.status.value}",
        )
    actor = Actor.from_request(request)

    # 拿 shipment 和 partner
    s = (await db.execute(
        select(Shipment).where(Shipment.id == br.shipment_id)
    )).scalar_one()
    p = (await db.execute(
        select(Partner).where(Partner.id == br.partner_id)
    )).scalar_one()

    # 渲染邮件
    template = (await db.execute(
        select(EmailTemplate).where(EmailTemplate.code == payload.template_code)
    )).scalar_one_or_none()
    if not template:
        raise HTTPException(
            status_code=400,
            detail=f"email template not found: {payload.template_code}",
        )

    context = {
        "booking_no": s.job_no,
        "carrier": s.current_carrier or "",
        "pol": br.requested_pol,
        "pod": br.requested_pod,
        "etd": br.requested_etd.isoformat() if br.requested_etd else "",
        "eta": (s.eta.isoformat() if s.eta else ""),
        "container_count": br.requested_container_count,
        "container_type": br.requested_container_type,
        "commodity": s.commodity,
        "weight_kg": s.weight_kg or "",
        "volume_cbm": s.volume_cbm or "",
        "customer_name": s.customer_partner.name if s.customer_partner else "",
        "customer_ref": s.customer_ref or "",
        "agent_name": s.operator_user_name or "二掌柜订舱",
    }
    body = render_template(template.subject, template.body, context)[1]
    raw_subject = render_template(template.subject, template.body, context)[0]
    # 自动加 [job_no] 前缀
    subject = f"[{s.job_no}] {raw_subject}" if not raw_subject.startswith("[") else raw_subject

    # 写 EmailLog
    email_log = EmailLog(
        template_code=payload.template_code,
        to_emails=payload.to_emails,
        cc_emails=payload.cc_emails,
        subject=subject,
        body=body,
        status=EmailStatus.SENT if not payload.dry_run else EmailStatus.PENDING,
        sent_at=datetime.now(timezone.utc) if not payload.dry_run else None,
        booking_id=s.id,  # v0.4 字段, 暂存, 阶段 2 切 shipment_id
    )
    db.add(email_log)
    await db.commit()
    await db.refresh(email_log)

    if not payload.dry_run:
        br.status = BookingRequestStatus.SENT
        br.sent_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(br)

    await write_audit_log(
        db,
        organization_id=br.organization_id,
        entity_type="booking_request",
        entity_id=br.id,
        action=AuditAction.SEND,
        actor=actor,
        field_changes={
            "to": payload.to_emails,
            "cc": payload.cc_emails,
            "subject": subject,
            "dry_run": payload.dry_run,
            "email_log_id": email_log.id,
        },
    )
    await db.commit()
    return BookingRequestRead.model_validate(br)


@router.post("/{br_id}/cancel", response_model=BookingRequestRead)
async def cancel_booking_request(
    br_id: str,
    payload: BookingRequestCancel,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> BookingRequestRead:
    br = (await db.execute(
        select(BookingRequest).where(BookingRequest.id == br_id)
    )).scalar_one_or_none()
    if not br:
        raise HTTPException(status_code=404, detail="booking_request not found")
    if br.status in (BookingRequestStatus.CANCELLED, BookingRequestStatus.CONFIRMED):
        raise HTTPException(
            status_code=400,
            detail=f"cannot cancel booking_request with status={br.status.value}",
        )
    actor = Actor.from_request(request)

    old_status = br.status
    br.status = BookingRequestStatus.CANCELLED
    br.cancelled_at = datetime.now(timezone.utc)
    br.cancellation_reason = payload.reason
    await db.commit()
    await db.refresh(br)

    await write_audit_log(
        db,
        organization_id=br.organization_id,
        entity_type="booking_request",
        entity_id=br.id,
        action=AuditAction.CANCEL,
        actor=actor,
        field_changes={"status": {"old": old_status.value, "new": "cancelled"}},
        reason=payload.reason,
    )
    await db.commit()
    return BookingRequestRead.model_validate(br)
