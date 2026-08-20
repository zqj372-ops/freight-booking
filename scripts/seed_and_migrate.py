"""一次性脚本: seed v0.4 真实数据 + 跑迁移 + 校验

用法: python -m scripts.seed_and_migrate
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# 加项目根到 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.booking import Booking, BookingStatus
from app.models.email_log import EmailLog, EmailStatus
from app.models.so import SO, SOStatus
from app.models.tracking import TrackingEvent, TrackingStatus, TrackingSource
from app.models.agent import Agent
from app.models.bill import Bill, BillKind, BillStatus
from app.models.shipment import Shipment
from app.models.partner import Partner, PartnerType
from app.models.document import Document
from app.models.booking_confirmation import BookingConfirmation
from app.models.legacy_entity_map import LegacyEntityMap
from app.services.migration import run_migration


async def seed_v04_data(db) -> dict:
    """seed 真实场景 v0.4 数据到 freight.db"""
    # 检查是否已 seed
    existing = (await db.execute(select(Booking))).scalars().all()
    if existing:
        print(f"  - v0.4 booking 已存在 ({len(existing)}), 跳过 seed")
        return {
            "agents": (await db.execute(select(Agent))).scalars().all().__len__(),
            "bookings": len(existing),
            "sos": (await db.execute(select(SO))).scalars().all().__len__(),
            "tracking": (await db.execute(select(TrackingEvent))).scalars().all().__len__(),
            "emails": (await db.execute(select(EmailLog))).scalars().all().__len__(),
            "bills": (await db.execute(select(Bill))).scalars().all().__len__(),
        }

    # 3 agents
    a1 = Agent(name="COSCO 华南一级代理", code="COSCO_S",
               contact_person="张总", contact_phone="13800138000",
               contact_email="zhang@cosco.example",
               booking_email="booking@cosco.example",
               cc_emails=["cc1@cosco.example", "cc2@cosco.example"],
               service_routes=["CNSZX-CAVAN", "CNSZX-CATOR"],
               notes="COSCO 主力代理", is_active=True)
    a2 = Agent(name="MAERSK 上海代理", code="MAES_S",
               contact_person="李经理", contact_phone="13900139000",
               contact_email="li@maersk.example",
               booking_email="booking@maersk.example",
               cc_emails=["ops@maersk.example"],
               service_routes=["CNSHA-CAVAN"],
               is_active=True)
    a3 = Agent(name="CMA 上海代理", code="CMA_S",
               contact_person="王总", contact_phone="13700137000",
               booking_email="booking@cma.example", is_active=True)
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
                 remark="客户要求配 COSCO 直航, 8/22 ETD")
    b2 = Booking(booking_no="V04-20260820-0002", pol="CNNGB", pod="CATOR",
                 etd=datetime(2026, 8, 21, tzinfo=timezone.utc),
                 eta=datetime(2026, 9, 18, tzinfo=timezone.utc),
                 container_type="40HQ", container_count=1, commodity="APPAREL",
                 weight_kg=8500, volume_cbm=32,
                 customer_name="BIG W", customer_ref="BIG-2026-077",
                 carrier="CMA", agent_id=a3.id,
                 status=BookingStatus.SUBMITTED)
    b3 = Booking(booking_no="V04-20260819-0014", pol="CNSHA", pod="CAVAN",
                 etd=datetime(2026, 8, 19, tzinfo=timezone.utc),
                 eta=datetime(2026, 9, 5, tzinfo=timezone.utc),
                 container_type="40HQ", container_count=2, commodity="FURNITURE",
                 weight_kg=22000, volume_cbm=48,
                 customer_name="HOME CO", customer_ref="HOME-2026-114",
                 carrier="MAERSK", agent_id=a2.id,
                 status=BookingStatus.COMPLETED)
    b4 = Booking(booking_no="V04-20260818-0008", pol="CNSZX", pod="CAVAN",
                 etd=datetime(2026, 8, 18, tzinfo=timezone.utc),
                 eta=datetime(2026, 9, 2, tzinfo=timezone.utc),
                 container_type="45HQ", container_count=1, commodity="TOY",
                 weight_kg=6500, volume_cbm=28,
                 customer_name="TOYS R US", customer_ref="TOY-2026-008",
                 carrier="MSC", agent_id=None,
                 status=BookingStatus.DRAFT)
    b5 = Booking(booking_no="V04-20260817-0003", pol="CNNGB", pod="CAYVR",
                 etd=datetime(2026, 8, 17, tzinfo=timezone.utc),
                 eta=datetime(2026, 8, 30, tzinfo=timezone.utc),
                 container_type="40HQ", container_count=1, commodity="AUTO PARTS",
                 weight_kg=18000, volume_cbm=22,
                 customer_name="AUTO SUPPLY", customer_ref="AUTO-2026-003",
                 carrier="COSCO", agent_id=a1.id,
                 status=BookingStatus.CANCELLED, remark="客户取消")
    db.add_all([b1, b2, b3, b4, b5])
    await db.flush()

    # 6 SOs
    so1 = SO(file_path="/data/so/so1.pdf", file_name="SO_0001.pdf",
             file_mime="application/pdf", file_size=102400, source="email",
             source_email="noreply@cosco.example",
             source_subject="SO 确认 - CAVAN",
             status=SOStatus.CONFIRMED, so_number="SO-123456",
             booking_number="V04-20260820-0001",
             vessel_name="COSCO SHIPPING", voyage_no="082E",
             pol="CNSZX", pod="CAVAN",
             etd=datetime(2026, 8, 22, tzinfo=timezone.utc),
             eta=datetime(2026, 9, 8, tzinfo=timezone.utc),
             cut_off=datetime(2026, 8, 21, 18, tzinfo=timezone.utc),
             container_type="40HQ", container_count=1,
             shipper="ACME Corp", consignee="CAVAN Logistics",
             commodity="ELECTRONIC", booking_id=b1.id,
             ocr_text="SO 082E COSCO SHIPPING 2026-08-22 ETD", ocr_engine="regex", ocr_confidence=0.95)
    so2 = SO(file_path="/data/so/so1_v2.pdf", file_name="SO_0001_v2.pdf",
             file_mime="application/pdf", file_size=110000, source="email",
             status=SOStatus.PENDING, booking_id=b1.id,
             vessel_name="COSCO SHIPPING", voyage_no="082E",
             etd=datetime(2026, 8, 22, tzinfo=timezone.utc),
             cut_off=datetime(2026, 8, 21, 18, tzinfo=timezone.utc))
    so3 = SO(file_path="/data/so/so2.pdf", file_name="SO_0002.pdf",
             file_mime="application/pdf", source="email", status=SOStatus.OCR_DONE,
             so_number="SO-789012", booking_id=b2.id, vessel_name="CMA CGM LOUVRE",
             voyage_no="0TN9CE1MA", etd=datetime(2026, 8, 21, tzinfo=timezone.utc),
             cut_off=datetime(2026, 8, 20, 12, tzinfo=timezone.utc))
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
             booking_id=None)
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
                      remark="船公司拒接改港"),
        TrackingEvent(booking_id=b5.id, status=TrackingStatus.BOOKED,
                      occurred_at=datetime(2026, 8, 16, 14, 0, tzinfo=timezone.utc)),
    ]
    db.add_all(events)

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

    await db.commit()
    return {
        "agents": 3, "bookings": 5, "sos": 6,
        "tracking": 12, "emails": 8, "bills": 3,
    }


async def main() -> None:
    print("=" * 60)
    print("seed_and_migrate: 准备 v0.4 真实数据 + 跑迁移")
    print("=" * 60)

    async with AsyncSessionLocal() as db:
        # Step 1: Seed v0.4
        print("\n[Step 1] seed v0.4 数据")
        seeded = await seed_v04_data(db)
        print(f"  ✓ v0.4 seeded: {seeded}")

        # Step 2: 跑迁移
        print("\n[Step 2] 跑 v0.4 → v0.5 迁移")
        result = await run_migration(db)
        print(f"  ✓ 迁移结果: {result}")

        # Step 3: 校验 v0.5 数据
        print("\n[Step 3] 校验 v0.5 数据")
        shipments = (await db.execute(select(Shipment))).scalars().all()
        partners = (await db.execute(select(Partner))).scalars().all()
        docs = (await db.execute(select(Document))).scalars().all()
        bcs = (await db.execute(select(BookingConfirmation))).scalars().all()
        maps = (await db.execute(select(LegacyEntityMap))).scalars().all()
        print(f"  ✓ v0.5 Shipments: {len(shipments)}")
        print(f"  ✓ v0.5 Partners: {len(partners)}")
        print(f"  ✓ v0.5 Documents: {len(docs)}")
        print(f"  ✓ v0.5 BookingConfirmations: {len(bcs)}")
        print(f"  ✓ LegacyEntityMap: {len(maps)}")

    print("\n" + "=" * 60)
    print("seed_and_migrate 完成 ✅")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
