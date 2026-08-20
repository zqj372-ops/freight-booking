"""v0.5 阶段 2 测试 - v0.4 → v0.5 数据迁移

测试设计:
- fixture: seed v0.4 数据 (3 agents + 5 bookings + 6 sos + 12 tracking + 8 emails + 3 bills)
- 跑 run_migration
- 验证 v0.5: 3 partners + 5 shipments + 6 documents + (CONFIRMED 数) booking_confirmations
  + milestones + email_messages + 完整 legacy_entity_map
- 验证 1 个 booking 全链路: legacy_job_no → shipment + SO + milestone + email
- 验证 idempotent: 跑 2 次不会重复
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.models.booking import Booking, BookingStatus
from app.models.booking_confirmation import BookingConfirmation
from app.models.container import Container
from app.models.document import Document
from app.models.email import EmailMessage
from app.models.email_log import EmailLog, EmailStatus
from app.models.legacy_entity_map import LegacyEntityMap
from app.models.milestone import Milestone
from app.models.partner import Partner, PartnerType
from app.models.shipment import Shipment
from app.models.so import SO, SOStatus
from app.models.tracking import TrackingEvent, TrackingStatus, TrackingSource
from app.models.agent import Agent
from app.models.bill import Bill, BillKind, BillStatus


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    from app.utils.bootstrap import seed_default_organization
    await seed_default_organization()
    yield


async def _seed_v04_data(db) -> dict:
    """建 v0.4 测试数据, 返回统计"""
    # 3 agents
    a1 = Agent(name="COSCO 华南代理", code="COSCO_S", contact_person="张总",
               contact_phone="13800138000", contact_email="zhang@cosco.example",
               booking_email="booking@cosco.example", cc_emails=["cc1@cosco.example"],
               service_routes=["CNSZX-CAVAN"], notes="一级代理", is_active=True)
    a2 = Agent(name="MAERSK 上海代理", code="MAES_S", contact_person="李经理",
               contact_phone="13900139000", contact_email="li@maersk.example",
               booking_email="booking@maersk.example", is_active=True)
    a3 = Agent(name="CMA 上海代理", code="CMA_S", contact_person="王总",
               booking_email="booking@cma.example", is_active=False)
    db.add_all([a1, a2, a3])
    await db.flush()

    # 5 bookings
    b1 = Booking(booking_no="V04-20260820-0001", pol="CNSZX", pod="CAVAN",
                 etd=datetime(2026, 8, 22, tzinfo=timezone.utc),
                 eta=datetime(2026, 9, 8, tzinfo=timezone.utc),
                 container_type="40HQ", container_count=1, commodity="ELECTRONIC",
                 weight_kg=12000, volume_cbm=25,
                 customer_name="ACME Corp", customer_ref="ACME-2026-001",
                 carrier="COSCO", agent_id=a1.id,
                 status=BookingStatus.CONFIRMED,
                 remark="客户要求配 COSCO 直航")
    b2 = Booking(booking_no="V04-20260820-0002", pol="CNNGB", pod="CATOR",
                 etd=datetime(2026, 8, 21, tzinfo=timezone.utc),
                 eta=datetime(2026, 9, 18, tzinfo=timezone.utc),
                 container_type="40HQ", container_count=1, commodity="APPAREL",
                 customer_name="BIG W", customer_ref="BIG-2026-077",
                 carrier="CMA", agent_id=a3.id,
                 status=BookingStatus.SUBMITTED)
    b3 = Booking(booking_no="V04-20260819-0014", pol="CNSHA", pod="CAVAN",
                 etd=datetime(2026, 8, 19, tzinfo=timezone.utc),
                 eta=datetime(2026, 9, 5, tzinfo=timezone.utc),
                 container_type="40HQ", container_count=2, commodity="FURNITURE",
                 customer_name="HOME CO", carrier="MAERSK", agent_id=a2.id,
                 status=BookingStatus.COMPLETED)
    b4 = Booking(booking_no="V04-20260818-0008", pol="CNSZX", pod="CAVAN",
                 etd=datetime(2026, 8, 18, tzinfo=timezone.utc),
                 eta=datetime(2026, 9, 2, tzinfo=timezone.utc),
                 container_type="45HQ", container_count=1, commodity="TOY",
                 customer_name="TOYS R US", carrier="MSC", agent_id=None,
                 status=BookingStatus.DRAFT)
    b5 = Booking(booking_no="V04-20260817-0003", pol="CNNGB", pod="CAYVR",
                 etd=datetime(2026, 8, 17, tzinfo=timezone.utc),
                 eta=datetime(2026, 8, 30, tzinfo=timezone.utc),
                 container_type="40HQ", container_count=1, commodity="AUTO PARTS",
                 customer_name="AUTO SUPPLY", carrier="COSCO", agent_id=a1.id,
                 status=BookingStatus.CANCELLED, remark="客户取消")
    db.add_all([b1, b2, b3, b4, b5])
    await db.flush()

    # 6 sos (b1 有 2 个, b2 有 1 个, b3 有 1 个, b4 0 个, b5 1 个, 1 个 unmatched)
    so1 = SO(file_path="/data/so/so1.pdf", file_name="SO_0001.pdf",
             file_mime="application/pdf", file_size=102400, source="email",
             source_email="noreply@cosco.example", source_subject="SO 确认 - CAVAN",
             status=SOStatus.CONFIRMED, so_number="SO-123456", booking_number="V04-20260820-0001",
             vessel_name="COSCO SHIPPING", voyage_no="082E",
             pol="CNSZX", pod="CAVAN",
             etd=datetime(2026, 8, 22, tzinfo=timezone.utc),
             eta=datetime(2026, 9, 8, tzinfo=timezone.utc),
             container_type="40HQ", container_count=1, shipper="ACME", consignee="CAVAN CO",
             commodity="ELECTRONIC", booking_id=b1.id,
             ocr_text="SO 082E COSCO SHIPPING 2026-08-22 ETD", ocr_engine="regex", ocr_confidence=0.95)
    so2 = SO(file_path="/data/so/so1_v2.pdf", file_name="SO_0001_v2.pdf",
             file_mime="application/pdf", file_size=110000, source="email",
             status=SOStatus.PENDING, booking_id=b1.id,  # 第二个 SO 未确认
             vessel_name="COSCO SHIPPING", voyage_no="082E", etd=datetime(2026, 8, 22, tzinfo=timezone.utc))
    so3 = SO(file_path="/data/so/so2.pdf", file_name="SO_0002.pdf",
             file_mime="application/pdf", source="email", status=SOStatus.OCR_DONE,
             so_number="SO-789012", booking_id=b2.id, vessel_name="CMA CGM LOUVRE",
             voyage_no="0TN9CE1MA", etd=datetime(2026, 8, 21, tzinfo=timezone.utc))
    so4 = SO(file_path="/data/so/so3.pdf", file_name="SO_0003.pdf",
             file_mime="application/pdf", source="upload", status=SOStatus.CONFIRMED,
             so_number="SO-MAE-001", booking_id=b3.id, vessel_name="MAERSK",
             voyage_no="631E", etd=datetime(2026, 8, 19, tzinfo=timezone.utc))
    so5 = SO(file_path="/data/so/so5.pdf", file_name="SO_0005.pdf",
             file_mime="application/pdf", source="email", status=SOStatus.OCR_DONE,
             so_number="SO-COSCO-005", booking_id=b5.id, vessel_name="COSCO",
             voyage_no="077E", etd=datetime(2026, 8, 17, tzinfo=timezone.utc))
    so6 = SO(file_path="/data/so/unmatched.pdf", file_name="SO_unmatched.pdf",
             file_mime="application/pdf", source="upload", status=SOStatus.PENDING,
             booking_id=None)  # 没匹配到 booking
    db.add_all([so1, so2, so3, so4, so5, so6])
    await db.flush()

    # 12 tracking events
    events = [
        TrackingEvent(booking_id=b1.id, status=TrackingStatus.BOOKED,
                      occurred_at=datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
                      source=TrackingSource.AUTO, remark="BC accepted"),
        TrackingEvent(booking_id=b1.id, status=TrackingStatus.EMPTY_PICKED_UP,
                      occurred_at=datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc),
                      container_no="COSU1234567", source=TrackingSource.MANUAL),
        TrackingEvent(booking_id=b1.id, status=TrackingStatus.LOADED,
                      occurred_at=datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc),
                      source=TrackingSource.AUTO),
        TrackingEvent(booking_id=b1.id, status=TrackingStatus.DEPARTED,
                      occurred_at=datetime(2026, 8, 22, 23, 0, tzinfo=timezone.utc),
                      vessel_name="COSCO SHIPPING", voyage_no="082E",
                      source=TrackingSource.AUTO),
        TrackingEvent(booking_id=b3.id, status=TrackingStatus.BOOKED,
                      occurred_at=datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)),
        TrackingEvent(booking_id=b3.id, status=TrackingStatus.DEPARTED,
                      occurred_at=datetime(2026, 8, 19, 22, 0, tzinfo=timezone.utc)),
        TrackingEvent(booking_id=b3.id, status=TrackingStatus.ARRIVED,
                      occurred_at=datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)),
        TrackingEvent(booking_id=b3.id, status=TrackingStatus.DELIVERED,
                      occurred_at=datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc)),
        TrackingEvent(booking_id=b3.id, status=TrackingStatus.COMPLETED,
                      occurred_at=datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)),
        TrackingEvent(booking_id=b2.id, status=TrackingStatus.BOOKED,
                      occurred_at=datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc)),
        TrackingEvent(booking_id=b2.id, status=TrackingStatus.EXCEPTION,
                      occurred_at=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
                      remark="船公司拒接改港"),  # EXCEPTION 跳过
        TrackingEvent(booking_id=b5.id, status=TrackingStatus.BOOKED,
                      occurred_at=datetime(2026, 8, 16, 14, 0, tzinfo=timezone.utc)),
    ]
    db.add_all(events)
    await db.flush()

    # 8 email logs
    emails = [
        EmailLog(template_code="booking_request", to_emails=["booking@cosco.example"],
                 subject=f"[订舱] {b1.booking_no}", body="申请订舱, 详见附件",
                 status=EmailStatus.SENT,
                 sent_at=datetime(2026, 8, 20, 9, 30, tzinfo=timezone.utc),
                 booking_id=b1.id),
        EmailLog(template_code="so_received", to_emails=["ops@2zhanghui.example"],
                 subject="【已收到】SO SO-123456", body="收到 COSCO 发送的 SO",
                 status=EmailStatus.SENT, sent_at=datetime(2026, 8, 20, 11, 30, tzinfo=timezone.utc),
                 booking_id=b1.id, so_id=so1.id),
        EmailLog(template_code="booking_request", to_emails=["booking@maersk.example"],
                 subject=f"[订舱] {b3.booking_no}", body="MAERSK 订舱",
                 status=EmailStatus.SENT, booking_id=b3.id),
        EmailLog(template_code="so_received", to_emails=["ops@2zhanghui.example"],
                 subject="【已收到】SO SO-MAE-001", body="已收到 MAERSK SO",
                 status=EmailStatus.SENT, booking_id=b3.id, so_id=so4.id),
        EmailLog(template_code="booking_request", to_emails=["booking@cma.example"],
                 subject=f"[订舱] {b2.booking_no}", body="CMA 订舱",
                 status=EmailStatus.FAILED, error="Connection refused",
                 booking_id=b2.id),
        EmailLog(template_code="bill_notification", to_emails=["billing@2zhanghui.example"],
                 subject=f"【账单】{b1.booking_no}", body="账单通知",
                 status=EmailStatus.PENDING, booking_id=b1.id),
        EmailLog(template_code="booking_request", to_emails=["booking@cosco.example"],
                 subject=f"[订舱] {b5.booking_no}", body="COSCO 订舱",
                 status=EmailStatus.SENT, booking_id=b5.id),
        EmailLog(template_code="customs_doc", to_emails=["customs@example"],
                 subject=f"[报关资料] {b1.booking_no}", body="报关资料",
                 status=EmailStatus.RETRYING, booking_id=b1.id),
    ]
    db.add_all(emails)
    await db.flush()

    # 3 bills
    bills = [
        Bill(booking_id=b1.id, bill_no="B-2026-0001", total_amount=1500.00,
             currency="USD", status=BillStatus.PAID, bill_kind=BillKind.OCEAN_FREIGHT,
             due_at=datetime(2026, 9, 1, tzinfo=timezone.utc)),
        Bill(booking_id=b1.id, bill_no="B-2026-0002", total_amount=500.00,
             currency="USD", status=BillStatus.UPLOADED, bill_kind=BillKind.DETENTION),
        Bill(booking_id=b3.id, bill_no="B-2026-0003", total_amount=2200.00,
             currency="USD", status=BillStatus.PAID, bill_kind=BillKind.OCEAN_FREIGHT),
    ]
    db.add_all(bills)
    await db.flush()

    return {
        "agents": 3, "bookings": 5, "sos": 5,  # so6 unmatched 跳过
        "tracking_events": 12, "email_logs": 8, "bills": 3,
    }


# ========== 测试 ==========


@pytest.mark.asyncio
async def test_migration_full_run() -> None:
    """完整跑一遍迁移, 验证 6 类计数"""
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        seeded = await _seed_v04_data(db)
        await db.commit()
        result = await run_migration(db)
        # 验证计数
        assert result["agents"] == seeded["agents"]
        assert result["bookings"] == seeded["bookings"]
        assert result["sos"] == seeded["sos"]
        # 12 - 1 EXCEPTION = 11 milestone
        assert result["tracking_events"] == 11
        assert result["email_logs"] == seeded["email_logs"]
        assert result["bills"] == seeded["bills"]


@pytest.mark.asyncio
async def test_migration_creates_partners() -> None:
    """agents → partners, partner_type=AGENT_L1"""
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        await _seed_v04_data(db)
        await db.commit()
        await run_migration(db)
        partners = (await db.execute(select(Partner))).scalars().all()
        assert len(partners) == 3
        for p in partners:
            assert p.partner_type == PartnerType.AGENT_L1
        # 联系信息映射
        cosco = next(p for p in partners if "COSCO" in p.name)
        assert cosco.contact_person == "张总"
        assert cosco.primary_email == "booking@cosco.example"
        assert cosco.cc_emails == ["cc1@cosco.example"]
        assert "CNSZX-CAVAN" in cosco.preferred_routes
        assert cosco.is_active is True
        # 失活的 agent 也迁
        cma = next(p for p in partners if "CMA" in p.name)
        assert cma.is_active is False


@pytest.mark.asyncio
async def test_migration_creates_shipments() -> None:
    """bookings → shipments + containers"""
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        await _seed_v04_data(db)
        await db.commit()
        await run_migration(db)
        shipments = (await db.execute(select(Shipment))).scalars().all()
        assert len(shipments) == 5
        # 找 booking V04-20260820-0001 (CONFIRMED) → stage=booked
        b1 = next(s for s in shipments if s.legacy_job_no == "V04-20260820-0001")
        assert b1.job_no == "V04-20260820-0001"  # 双留
        assert b1.pol == "CNSZX"
        assert b1.pod == "CAVAN"
        assert b1.current_carrier == "COSCO"
        assert b1.stage.value == "booked"  # CONFIRMED → booked
        assert b1.customer_name == "ACME Corp"
        # current_partner_id 指向 COSCO partner
        assert b1.current_partner_id is not None
        cosco_partner = (await db.execute(
            select(Partner).where(Partner.id == b1.current_partner_id)
        )).scalar_one()
        assert "COSCO" in cosco_partner.name
        # 容器自动建
        containers = (await db.execute(
            select(Container).where(Container.shipment_id == b1.id)
        )).scalars().all()
        assert len(containers) == 1
        assert containers[0].container_type == "40HQ"

        # booking V04-20260817-0003 (CANCELLED) → stage=cancelled
        b5 = next(s for s in shipments if s.legacy_job_no == "V04-20260817-0003")
        assert b5.stage.value == "cancelled"
        assert b5.remark == "客户取消"

        # booking V04-20260819-0014 (COMPLETED) → stage=completed
        b3 = next(s for s in shipments if s.legacy_job_no == "V04-20260819-0014")
        assert b3.stage.value == "completed"


@pytest.mark.asyncio
async def test_migration_creates_documents_and_confirmations() -> None:
    """sos → documents, CONFIRMED 的额外建 booking_confirmations"""
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        await _seed_v04_data(db)
        await db.commit()
        await run_migration(db)
        docs = (await db.execute(select(Document))).scalars().all()
        # 5 个 SO 有 shipment_id, unmatched 跳过
        assert len(docs) == 5
        bcs = (await db.execute(select(BookingConfirmation))).scalars().all()
        # 2 个 SO 是 CONFIRMED: so1, so4 (so2/so3/so5 都是 OCR_DONE, so6 unmatched)
        assert len(bcs) == 2
        for bc in bcs:
            assert bc.is_current is True
            assert bc.status.value == "accepted"
            assert bc.version == 1
        # 验证 BC.so_no 包含 2 个 CONFIRMED SO 的 so_number
        bcs_by_no = {bc.so_no: bc for bc in bcs}
        assert "SO-123456" in bcs_by_no  # so1
        assert "SO-MAE-001" in bcs_by_no  # so4
        # 没 BC 字段 (so3/so5 是 OCR_DONE, 没建 BC)
        bcs_by_no_unmatch = [bc for bc in bcs if bc.so_no in ("SO-789012", "SO-COSCO-005")]
        assert len(bcs_by_no_unmatch) == 0
        for bc in bcs:
            assert bc.is_current is True
            assert bc.status.value == "accepted"
            assert bc.version == 1
        # so1 → BC.so_no=SO-123456
        bcs_by_no = {bc.so_no: bc for bc in bcs}
        assert "SO-123456" in bcs_by_no
        assert "SO-MAE-001" in bcs_by_no
        assert "SO-COSCO-005" not in bcs_by_no  # so5 是 OCR_DONE, 不应建 BC


@pytest.mark.asyncio
async def test_migration_creates_milestones() -> None:
    """tracking_events → milestones, EXCEPTION 跳过"""
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        await _seed_v04_data(db)
        await db.commit()
        await run_migration(db)
        milestones = (await db.execute(select(Milestone))).scalars().all()
        # 12 - 1 EXCEPTION = 11
        assert len(milestones) == 11
        # b1 4 个 milestone (booked, empty_picked_up, loaded, departed)
        b1_ship = (await db.execute(
            select(Shipment).where(Shipment.legacy_job_no == "V04-20260820-0001")
        )).scalar_one()
        b1_ms = (await db.execute(
            select(Milestone).where(Milestone.shipment_id == b1_ship.id)
        )).scalars().all()
        assert len(b1_ms) == 4
        codes = {m.code.value for m in b1_ms}
        assert "booking_confirmation_accepted" in codes
        assert "container_picked_up" in codes
        assert "container_loaded" in codes
        assert "departed" in codes


@pytest.mark.asyncio
async def test_migration_creates_email_messages() -> None:
    """email_logs → email_messages (outbound)"""
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        await _seed_v04_data(db)
        await db.commit()
        await run_migration(db)
        msgs = (await db.execute(select(EmailMessage))).scalars().all()
        assert len(msgs) == 8
        for m in msgs:
            assert m.direction == "outbound"
        # 关联: b1 有 3 个 email (booking_request/so_received/bill_notification/customs_doc)
        b1_ship = (await db.execute(
            select(Shipment).where(Shipment.legacy_job_no == "V04-20260820-0001")
        )).scalar_one()
        b1_msgs = [m for m in msgs if m.matched_shipment_id == b1_ship.id]
        assert len(b1_msgs) == 4
        # FAILED 映射
        failed = next(m for m in msgs if m.error and "Connection refused" in m.error)
        assert failed.status.value == "failed"


@pytest.mark.asyncio
async def test_migration_bills_to_v5() -> None:
    """bills → bills_v5 (v0.5 阶段 1.5.5 补: 不再 skipped)"""
    from app.services.migration import run_migration
    from app.models.bill_v5 import BillV5

    async with AsyncSessionLocal() as db:
        await _seed_v04_data(db)
        await db.commit()
        await run_migration(db)
        # bills_v5 表有 3 行
        bills_v5 = (await db.execute(select(BillV5))).scalars().all()
        assert len(bills_v5) == 3
        # 找 bill map: v04_type=bill, v05_type=bill (不再 skipped)
        bill_maps = (await db.execute(
            select(LegacyEntityMap).where(
                LegacyEntityMap.v04_type == "bill",
                LegacyEntityMap.v05_type == "bill",
            )
        )).scalars().all()
        assert len(bill_maps) == 3
        for m in bill_maps:
            assert m.v05_id is not None
            assert "bill_no" in m.context
        # 3 个 v0.4 bills 现在有 0 个 skipped
        skipped_bill_maps = (await db.execute(
            select(LegacyEntityMap).where(
                LegacyEntityMap.v04_type == "bill",
                LegacyEntityMap.v05_type == "skipped",
            )
        )).scalars().all()
        assert len(skipped_bill_maps) == 0


@pytest.mark.asyncio
async def test_migration_legacy_entity_map_complete() -> None:
    """LegacyEntityMap 完整记录所有映射"""
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        seeded = await _seed_v04_data(db)
        await db.commit()
        await run_migration(db)
        maps = (await db.execute(select(LegacyEntityMap))).scalars().all()
        # 总数: 3 agents + 5 bookings + 5 SO docs + 2 SO BCs + 12 tracking + 8 emails + 3 bills = 38
        assert len(maps) == 3 + 5 + 5 + 2 + 12 + 8 + 3
        # 按 type 分组
        by_type: dict[str, list] = {}
        for m in maps:
            by_type.setdefault(m.v04_type, []).append(m)
        assert len(by_type["agent"]) == 3
        assert len(by_type["booking"]) == 5
        assert len(by_type["so"]) == 7  # 5 doc + 2 BC
        assert len(by_type["tracking_event"]) == 12
        assert len(by_type["email_log"]) == 8
        assert len(by_type["bill"]) == 3
        # 1.5.5: bill 现在 v05_type=bill (不再 skipped)
        bill_migrated = [m for m in by_type["bill"] if m.v05_type == "bill"]
        assert len(bill_migrated) == 3
        for m in bill_migrated:
            assert m.v05_id is not None
        # 1 个 tracking 仍标记为 skipped
        skipped_tracking = [m for m in by_type["tracking_event"] if m.v05_type == "skipped"]
        assert len(skipped_tracking) == 1
        assert "exception" in skipped_tracking[0].context["reason"].lower()
        # 1 个 tracking 标记为 skipped
        skipped_tracking = [m for m in by_type["tracking_event"] if m.v05_type == "skipped"]
        assert len(skipped_tracking) == 1
        assert "exception" in skipped_tracking[0].context["reason"].lower()


@pytest.mark.asyncio
async def test_migration_idempotent() -> None:
    """跑 2 次迁移不会重复"""
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        await _seed_v04_data(db)
        await db.commit()
        result1 = await run_migration(db)
        result2 = await run_migration(db)
        # 第二次全部 0
        assert result2["agents"] == 0
        assert result2["bookings"] == 0
        assert result2["sos"] == 0
        assert result2["tracking_events"] == 0
        assert result2["email_logs"] == 0
        assert result2["bills"] == 0
        # 实体没翻倍
        partners = (await db.execute(select(Partner))).scalars().all()
        assert len(partners) == 3
        shipments = (await db.execute(select(Shipment))).scalars().all()
        assert len(shipments) == 5


@pytest.mark.asyncio
async def test_migration_full_chain_lookup() -> None:
    """从 v0.4 booking_id 查完整 v0.5 链路: shipment + BC + document + milestone + email"""
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        await _seed_v04_data(db)
        await db.commit()
        await run_migration(db)
        # 找 b1 的 v0.5 shipment (via legacy map)
        from app.models.booking import Booking
        v04_b1 = (await db.execute(
            select(Booking).where(Booking.booking_no == "V04-20260820-0001")
        )).scalar_one()
        b1_map = (await db.execute(
            select(LegacyEntityMap).where(
                LegacyEntityMap.v04_type == "booking",
                LegacyEntityMap.v04_id == v04_b1.id,
            )
        )).scalar_one()
        v05_ship_id = b1_map.v05_id
        # shipment
        ship = (await db.execute(
            select(Shipment).where(Shipment.id == v05_ship_id)
        )).scalar_one()
        assert ship.legacy_job_no == "V04-20260820-0001"
        # booking confirmation (1 个 CONFIRMED SO → 1 BC)
        bcs = (await db.execute(
            select(BookingConfirmation).where(BookingConfirmation.shipment_id == v05_ship_id)
        )).scalars().all()
        assert len(bcs) == 1
        # document (2 个 SO → 2 doc)
        docs = (await db.execute(
            select(Document).where(Document.shipment_id == v05_ship_id)
        )).scalars().all()
        assert len(docs) == 2
        # milestone (4 个)
        ms = (await db.execute(
            select(Milestone).where(Milestone.shipment_id == v05_ship_id)
        )).scalars().all()
        assert len(ms) == 4
        # email (4 个)
        from app.models.email import EmailMessage
        emails = (await db.execute(
            select(EmailMessage).where(EmailMessage.matched_shipment_id == v05_ship_id)
        )).scalars().all()
        assert len(emails) == 4
