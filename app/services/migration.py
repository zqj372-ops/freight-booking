"""v0.5 阶段 2: v0.4 → v0.5 数据迁移

5 类迁移:
1. agents → partners (partner_type=AGENT_L1)
2. bookings → shipments + containers
3. sos → documents (+ booking_confirmations 当 CONFIRMED)
4. tracking_events → milestones (按 status 映射)
5. email_logs → email_messages

1 类 skipped:
- bills → LegacyEntityMap (v05_type=skipped, v0.5 暂不建 Bill 表)

约束:
- 一次性脚本, 不重入 (idempotent 通过 LegacyEntityMap 唯一索引)
- v0.4 表保留 (read-only 兼容层, /api/v1 继续用)
- 不写 audit_log (迁移不是业务操作)

用法:
    from app.services.migration import run_migration
    result = await run_migration(db, org_id)
    print(result)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.organization_context import get_default_organization
from app.models.agent import Agent
from app.models.booking import Booking, BookingStatus
from app.models.booking_confirmation import (
    BookingConfirmation, BookingConfirmationStatus,
)
from app.models.container import Container
from app.models.document import (
    Document, DocumentSource, DocumentType, OcrStatus, ParseStatus,
)
from app.models.email import (
    EmailMessage, EmailMessageStatus, EmailSource, EmailThread, EmailThreadStatus,
)
from app.models.email_log import EmailLog, EmailStatus
from app.models.legacy_entity_map import LegacyEntityMap
from app.models.milestone import Milestone, MilestoneCode, MilestoneSource
from app.models.partner import Partner, PartnerType
from app.models.shipment import Shipment, ShipmentStage
from app.models.so import SO, SOStatus
from app.models.tracking import TrackingEvent, TrackingStatus


# ========== 字段映射常量 ==========

# TrackingStatus → MilestoneCode (v0.5 阶段 1 16 个 code)
TRACKING_TO_MILESTONE: dict[TrackingStatus, MilestoneCode | None] = {
    TrackingStatus.BOOKED: MilestoneCode.BOOKING_CONFIRMATION_ACCEPTED,
    TrackingStatus.EMPTY_PICKED_UP: MilestoneCode.CONTAINER_PICKED_UP,
    TrackingStatus.LOADED: MilestoneCode.CONTAINER_LOADED,
    TrackingStatus.DEPARTED: MilestoneCode.DEPARTED,
    TrackingStatus.IN_TRANSIT: MilestoneCode.IN_TRANSIT,
    TrackingStatus.ARRIVED: MilestoneCode.ARRIVED_AT_POD,
    TrackingStatus.DELIVERED: MilestoneCode.DELIVERED,
    TrackingStatus.COMPLETED: MilestoneCode.EMPTY_RETURNED,
    TrackingStatus.EXCEPTION: None,  # 异常节点不直接转 milestone, 走 OperationalException
}

# BookingStatus → ShipmentStage
BOOKING_TO_SHIPMENT_STAGE: dict[BookingStatus, ShipmentStage] = {
    BookingStatus.DRAFT: ShipmentStage.DRAFT,
    BookingStatus.SUBMITTED: ShipmentStage.BOOKING_IN_PROGRESS,
    BookingStatus.CONFIRMED: ShipmentStage.BOOKED,
    BookingStatus.REJECTED: ShipmentStage.CANCELLED,
    BookingStatus.CANCELLED: ShipmentStage.CANCELLED,
    BookingStatus.COMPLETED: ShipmentStage.COMPLETED,
}

# SOStatus → (OcrStatus, 是否建 BookingConfirmation)
SO_TO_OCR: dict[SOStatus, OcrStatus] = {
    SOStatus.PENDING: OcrStatus.PENDING,
    SOStatus.OCR_DONE: OcrStatus.DONE,
    SOStatus.OCR_FAILED: OcrStatus.FAILED,
    SOStatus.CONFIRMED: OcrStatus.DONE,  # 隐含 OCR done
    SOStatus.REJECTED: OcrStatus.DONE,
}

# EmailStatus → EmailMessageStatus
EMAIL_TO_MESSAGE_STATUS: dict[EmailStatus, EmailMessageStatus] = {
    EmailStatus.PENDING: EmailMessageStatus.QUEUED,
    EmailStatus.SENT: EmailMessageStatus.SENT,
    EmailStatus.FAILED: EmailMessageStatus.FAILED,
    EmailStatus.RETRYING: EmailMessageStatus.QUEUED,  # v0.5 简化为 queued
}


# ========== 辅助函数 ==========


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


async def _already_mapped(
    db: AsyncSession, organization_id: str, v04_type: str, v04_id: str,
    v05_type: str | None = None,
) -> LegacyEntityMap | None:
    """查是否已迁过 (idempotent guard). 1 个 v04 实体可对应多个 v05 实体 (e.g. SO → Doc + BC)"""
    stmt = select(LegacyEntityMap).where(
        LegacyEntityMap.organization_id == organization_id,
        LegacyEntityMap.v04_type == v04_type,
        LegacyEntityMap.v04_id == v04_id,
    )
    if v05_type is not None:
        stmt = stmt.where(LegacyEntityMap.v05_type == v05_type)
    # 用 first() 而非 scalar_one_or_none, 因为 SO 可对应 2 行 (doc + BC)
    rows = (await db.execute(stmt)).scalars().all()
    return rows[0] if rows else None


async def _record_map(
    db: AsyncSession,
    organization_id: str,
    v04_type: str,
    v04_id: str,
    v05_type: str,
    v05_id: str | None,
    context: dict[str, Any] | None = None,
) -> LegacyEntityMap:
    """写一条 legacy map (假设已确认未迁过)"""
    m = LegacyEntityMap(
        organization_id=organization_id,
        v04_type=v04_type,
        v04_id=v04_id,
        v05_type=v05_type,
        v05_id=v05_id,
        context=context,
        mapped_at=_now(),
    )
    db.add(m)
    return m


# ========== 5 类迁移函数 ==========


async def migrate_agents(db: AsyncSession, organization_id: str) -> int:
    """agents → partners (AGENT_L1)"""
    agents = (await db.execute(select(Agent))).scalars().all()
    count = 0
    for a in agents:
        if await _already_mapped(db, organization_id, "agent", a.id):
            continue
        p = Partner(
            id=_new_id(),
            organization_id=organization_id,
            name=a.name,
            short_code=a.code,
            partner_type=PartnerType.AGENT_L1,
            contact_person=a.contact_person,
            contact_phone=a.contact_phone,
            primary_email=a.booking_email,
            contact_wechat=a.contact_wechat,
            cc_emails=a.cc_emails or [],
            preferred_routes=a.service_routes or [],
            remark=a.notes,
            is_active=a.is_active,
        )
        db.add(p)
        await _record_map(db, organization_id, "agent", a.id, "partner", p.id, {
            "name": a.name, "code": a.code,
        })
        count += 1
    await db.flush()
    logger.info("migrated {} agents → partners", count)
    return count


async def migrate_bookings(db: AsyncSession, organization_id: str) -> int:
    """bookings → shipments + containers"""
    bookings = (await db.execute(select(Booking))).scalars().all()
    count = 0
    for b in bookings:
        if await _already_mapped(db, organization_id, "booking", b.id):
            continue
        # target_etd: v0.4 booking.etd 若是 date 转 date; v0.4 etd 是 datetime → date
        target_etd = b.etd.date() if b.etd else _now().date()

        # 找 current_partner (从 agent map)
        current_partner_id = None
        if b.agent_id:
            map_row = await _already_mapped(db, organization_id, "agent", b.agent_id)
            if map_row and map_row.v05_id:
                current_partner_id = map_row.v05_id

        s = Shipment(
            id=_new_id(),
            organization_id=organization_id,
            job_no=b.booking_no,
            legacy_job_no=b.booking_no,  # 双留, 兼容
            stage=BOOKING_TO_SHIPMENT_STAGE.get(b.status, ShipmentStage.DRAFT),
            etd=b.etd.date() if b.etd else None,
            eta=b.eta.date() if b.eta else None,
            target_etd=target_etd,
            pol=b.pol, pod=b.pod,
            commodity=b.commodity or "未指定",
            container_count=b.container_count or 1,
            weight_kg=b.weight_kg,
            volume_cbm=b.volume_cbm,
            customer_name=b.customer_name,
            customer_ref=b.customer_ref,
            current_carrier=b.carrier,
            current_partner_id=current_partner_id,
            remark=b.remark,
        )
        db.add(s)

        # 自动建 1 柜 (v0.5 强制 1)
        c = Container(
            id=_new_id(),
            organization_id=organization_id,
            shipment_id=s.id,
            container_type=b.container_type or "40HQ",
        )
        db.add(c)

        await _record_map(db, organization_id, "booking", b.id, "shipment", s.id, {
            "booking_no": b.booking_no, "carrier": b.carrier,
        })
        count += 1
    await db.flush()
    logger.info("migrated {} bookings → shipments", count)
    return count


async def migrate_sos(db: AsyncSession, organization_id: str) -> int:
    """sos → documents (+ booking_confirmations if CONFIRMED)"""
    sos = (await db.execute(select(SO))).scalars().all()
    count = 0
    for so in sos:
        if await _already_mapped(db, organization_id, "so", so.id):
            continue

        # 找 shipment (from booking_id)
        shipment_id = None
        if so.booking_id:
            map_row = await _already_mapped(db, organization_id, "booking", so.booking_id)
            if map_row and map_row.v05_id:
                shipment_id = map_row.v05_id

        if not shipment_id:
            logger.warning("SO {} has no shipment, skip document", so.id)
            continue

        # 1. 建 Document
        doc = Document(
            id=_new_id(),
            organization_id=organization_id,
            shipment_id=shipment_id,
            filename=so.file_name,
            file_path=so.file_path,
            mime_type=so.file_mime or "application/pdf",
            file_size=so.file_size or 0,
            file_hash=f"v04_migrated_{so.id}",  # 假的 hash, 避免 unique 冲突
            source=(
                DocumentSource.IMAP_ATTACHMENT
                if so.source == "email"
                else DocumentSource.MANUAL_UPLOAD
            ),
            doc_type=DocumentType.SO,
            ocr_status=SO_TO_OCR.get(so.status, OcrStatus.PENDING),
            ocr_text=so.ocr_text,
            ocr_engine=so.ocr_engine,
            ocr_confidence=so.ocr_confidence,
            ocr_at=so.ocr_at,
            ocr_error=so.ocr_error,
            parse_status=ParseStatus.MATCHED_BOOKING if shipment_id else ParseStatus.UNMATCHED,
            uploaded_at=so.created_at,
        )
        db.add(doc)
        await _record_map(db, organization_id, "so", so.id, "document", doc.id, {
            "so_number": so.so_number, "carrier": so.carrier,
        })

        # 2. 如果 SO CONFIRMED → 建 BookingConfirmation
        if so.status == SOStatus.CONFIRMED:
            # 找 v0.5 current_bc: 该 shipment 还没 BC, 所以这是第一个, version=1 is_current=True
            bc = BookingConfirmation(
                id=_new_id(),
                organization_id=organization_id,
                shipment_id=shipment_id,
                booking_request_id=None,  # v0.4 没有 BR
                document_id=doc.id,
                version=1,
                is_current=True,
                status=BookingConfirmationStatus.ACCEPTED,
                so_no=so.so_number,
                bl_no=so.bl_number,
                carrier=so.carrier,
                vessel_name=so.vessel_name,
                voyage_no=so.voyage_no,
                pol=so.pol,
                pod=so.pod,
                etd=so.etd.date() if so.etd else None,
                eta=so.eta.date() if so.eta else None,
                si_cutoff_at=so.cut_off,
                container_type=so.container_type,
                container_count=so.container_count,
                accepted_at=so.created_at,
            )
            db.add(bc)
            await _record_map(
                db, organization_id, "so", so.id, "booking_confirmation", bc.id,
                {"version": 1, "is_current": True},
            )
        count += 1
    await db.flush()
    logger.info("migrated {} sos → documents", count)
    return count


async def migrate_tracking_events(db: AsyncSession, organization_id: str) -> int:
    """tracking_events → milestones (按 status 映射)"""
    events = (await db.execute(select(TrackingEvent))).scalars().all()
    count = 0
    skipped = 0
    for ev in events:
        if await _already_mapped(db, organization_id, "tracking_event", ev.id):
            continue

        # 找 shipment
        map_row = await _already_mapped(db, organization_id, "booking", ev.booking_id)
        if not map_row or not map_row.v05_id:
            skipped += 1
            continue
        shipment_id = map_row.v05_id

        # 映射 status → milestone code
        code = TRACKING_TO_MILESTONE.get(ev.status)
        if not code:
            # EXCEPTION 类型, 不建 milestone, 写 skip map
            await _record_map(
                db, organization_id, "tracking_event", ev.id, "skipped", None,
                {"reason": f"tracking_status={ev.status.value} has no milestone equivalent"},
            )
            skipped += 1
            continue

        m = Milestone(
            id=_new_id(),
            organization_id=organization_id,
            shipment_id=shipment_id,
            code=code,
            occurred_at=ev.occurred_at,
            recorded_at=ev.occurred_at,
            source=MilestoneSource.MANUAL,  # v0.4 简单起见
            location=ev.location,
            vessel_name=ev.vessel_name,
            voyage_no=ev.voyage_no,
            container_no=ev.container_no,
            remark=ev.remark,
        )
        db.add(m)
        await _record_map(
            db, organization_id, "tracking_event", ev.id, "milestone", m.id,
            {"v04_status": ev.status.value, "v05_code": code.value},
        )
        count += 1
    await db.flush()
    logger.info("migrated {} tracking_events → milestones ({} skipped)", count, skipped)
    return count


async def migrate_email_logs(db: AsyncSession, organization_id: str) -> int:
    """email_logs → email_messages (outbound)"""
    logs = (await db.execute(select(EmailLog))).scalars().all()
    count = 0
    for log in logs:
        if await _already_mapped(db, organization_id, "email_log", log.id):
            continue

        # 找 shipment
        shipment_id = None
        if log.booking_id:
            map_row = await _already_mapped(db, organization_id, "booking", log.booking_id)
            if map_row and map_row.v05_id:
                shipment_id = map_row.v05_id

        # v0.5 必填 thread_id, 给每个 email_log 建独立 stub thread
        thread = EmailThread(
            id=_new_id(),
            organization_id=organization_id,
            subject=log.subject,
            subject_prefix=log.template_code,  # v0.4 template_code 存这里
            status=EmailThreadStatus.ACTIVE,
        )
        db.add(thread)
        await db.flush()

        em = EmailMessage(
            id=_new_id(),
            organization_id=organization_id,
            thread_id=thread.id,
            matched_shipment_id=shipment_id,
            direction="outbound",  # v0.4 email_log 是发出去的
            from_addr=log.to_emails[0] if log.to_emails else "ops@2zhanghui.example",
            to_addrs=log.to_emails or [],
            cc_addrs=log.cc_emails or [],
            subject=log.subject,
            body_text=log.body,
            status=EMAIL_TO_MESSAGE_STATUS.get(log.status, EmailMessageStatus.QUEUED),
            sent_at=log.sent_at,
            error=log.error,
            retry_count=log.retry_count,
            source=EmailSource.MANUAL,
        )
        db.add(em)
        await _record_map(
            db, organization_id, "email_log", log.id, "email_message", em.id,
            {"template_code": log.template_code, "subject": log.subject[:50]},
        )
        count += 1
    await db.flush()
    logger.info("migrated {} email_logs → email_messages", count)
    return count


async def migrate_bills(db: AsyncSession, organization_id: str) -> int:
    """bills → bills_v5 (v0.5 阶段 1.5.5 补: 不再 skipped)

    字段映射:
    - bill_no → bill_no
    - bill_type (v0.4 String) → bill_type (v0.5 Enum)
    - bill_kind (v0.4 Enum) → bill_kind (v0.5 Enum, 同名)
    - booking_id → shipment_id (via legacy map)
    - matched_booking_id → matched_shipment_id (via legacy map)
    - status (v0.4 Enum) → status (v0.5 Enum, 字符串值相同 → 直接转)
    - total_amount/tax_amount/amount_excl_tax/currency/file_* → 同名
    - ocr_* → 同名
    - issued_at/due_at/paid_at → 同名
    - matched_at/match_score → 同名
    - payment_method/payment_ref → 同名
    - remark → remark
    - line_items/extra_fields → 同名
    """
    from app.models.bill import Bill  # noqa
    from app.models.bill_v5 import (
        BillV5, BillKind, BillStatus, BillType,
    )

    # 找 v0.5 BillStatus enum (同名) 兼容
    v04_to_v05_status = {
        "uploaded": BillStatus.UPLOADED,
        "ocr_processing": BillStatus.OCR_PROCESSING,
        "ocr_done": BillStatus.OCR_DONE,
        "ocr_failed": BillStatus.OCR_FAILED,
        "confirmed": BillStatus.CONFIRMED,
        "disputed": BillStatus.DISPUTED,
        "paid": BillStatus.PAID,
    }

    bills = (await db.execute(select(Bill))).scalars().all()
    count = 0
    for b in bills:
        if await _already_mapped(db, organization_id, "bill", b.id):
            continue

        # 找 shipment (从 booking map)
        shipment_id = None
        if b.booking_id:
            map_row = await _already_mapped(db, organization_id, "booking", b.booking_id)
            if map_row and map_row.v05_id:
                shipment_id = map_row.v05_id

        matched_shipment_id = None
        if b.matched_booking_id:
            map_row = await _already_mapped(db, organization_id, "booking", b.matched_booking_id)
            if map_row and map_row.v05_id:
                matched_shipment_id = map_row.v05_id

        # bill_type
        bill_type = BillType.RECEIVABLE
        if hasattr(b, "bill_type") and b.bill_type:
            try:
                bill_type = BillType(b.bill_type)
            except ValueError:
                bill_type = BillType.RECEIVABLE

        # bill_kind (v0.4 已是同名 Enum)
        bill_kind = BillKind.OTHER
        if hasattr(b, "bill_kind") and b.bill_kind:
            try:
                bill_kind = BillKind(b.bill_kind.value if hasattr(b.bill_kind, "value") else b.bill_kind)
            except (ValueError, AttributeError):
                bill_kind = BillKind.OTHER

        # status
        v05_status = BillStatus.UPLOADED
        v04_status_str = b.status.value if hasattr(b.status, "value") else str(b.status)
        v05_status = v04_to_v05_status.get(v04_status_str, BillStatus.UPLOADED)

        new_bill = BillV5(
            id=_new_id(),
            organization_id=organization_id,
            bill_no=b.bill_no,
            bill_type=bill_type,
            bill_kind=bill_kind,
            shipment_id=shipment_id,
            matched_shipment_id=matched_shipment_id,
            seller_name=b.seller_name,
            seller_tax_no=b.seller_tax_no,
            buyer_name=b.buyer_name,
            buyer_tax_no=b.buyer_tax_no,
            currency=b.currency or "CNY",
            total_amount=b.total_amount,
            tax_amount=b.tax_amount,
            amount_excl_tax=b.amount_excl_tax,
            file_path=b.file_path,
            file_name=b.file_name,
            file_mime=b.file_mime,
            file_size=b.file_size or 0,
            ocr_text=b.ocr_text,
            ocr_engine=b.ocr_engine,
            ocr_confidence=b.ocr_confidence,
            ocr_error=b.ocr_error,
            ocr_at=b.ocr_at,
            line_items=b.line_items or [],
            extra_fields=b.extra_fields or {},
            status=v05_status,
            issued_at=b.issued_at,
            due_at=b.due_at,
            paid_at=b.paid_at,
            matched_at=b.matched_at,
            match_score=b.match_score,
            payment_method=b.payment_method,
            payment_ref=b.payment_ref,
            remark=b.remark,
        )
        db.add(new_bill)
        await _record_map(
            db, organization_id, "bill", b.id, "bill", new_bill.id,
            {
                "bill_no": b.bill_no,
                "total_amount": float(b.total_amount) if b.total_amount else None,
                "currency": b.currency,
                "v04_status": v04_status_str,
                "v05_status": v05_status.value,
            },
        )
        count += 1
    await db.flush()
    logger.info("migrated {} bills → bills_v5", count)
    return count


# ========== 主入口 ==========


async def run_migration(db: AsyncSession, organization_id: str | None = None) -> dict[str, int]:
    """v0.4 → v0.5 全量迁移, 返回各类计数.

    organization_id: 不传则取默认 organization.
    """
    if not organization_id:
        org = await get_default_organization(db)
        organization_id = org.id

    logger.info("=== v0.4 → v0.5 migration START (org={}) ===", organization_id)
    result: dict[str, int] = {}

    # 顺序: agents → bookings → sos → tracking → emails → bills
    # (依赖: bookings 依赖 agents, sos/tracking/emails 依赖 bookings)
    result["agents"] = await migrate_agents(db, organization_id)
    result["bookings"] = await migrate_bookings(db, organization_id)
    result["sos"] = await migrate_sos(db, organization_id)
    result["tracking_events"] = await migrate_tracking_events(db, organization_id)
    result["email_logs"] = await migrate_email_logs(db, organization_id)
    result["bills"] = await migrate_bills(db, organization_id)

    await db.commit()
    logger.info("=== v0.4 → v0.5 migration DONE: {} ===", result)
    return result
