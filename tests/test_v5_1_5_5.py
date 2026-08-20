"""v0.5 阶段 1.5.5 测试 - Document 状态机 + Bill v0.5 model + 迁移"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.bill_v5 import BillKind, BillStatus, BillType, BillV5
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.legacy_entity_map import LegacyEntityMap


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    from app.utils.bootstrap import seed_default_organization, seed_default_templates
    await seed_default_organization()
    await seed_default_templates()
    yield


async def _post(client, path, json=None, headers=None):
    r = await client.post(path, json=json or {}, headers=headers or {})
    assert r.status_code in (200, 201), f"{path}: {r.status_code} {r.text}"
    return r.json()


async def _patch(client, path, json=None, headers=None):
    r = await client.patch(path, json=json or {}, headers=headers or {})
    assert r.status_code in (200, 201), f"PATCH {path}: {r.status_code} {r.text}"
    return r.json()


# ========== Document 状态机 ==========


@pytest.mark.asyncio
async def test_document_status_default_uploaded() -> None:
    """新建 Document, status 默认 uploaded"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 用 multipart upload (简化: 直接 ORM 创一个 Document)
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            doc = Document(
                organization_id=s["organization_id"],
                shipment_id=s["id"],
                filename="test.pdf", file_path="/tmp/test.pdf",
                file_hash="test_hash_001",
                mime_type="application/pdf", file_size=1024,
                source="manual_upload",
                doc_type=DocumentType.SO,
                ocr_status="pending",
                parse_status="unmatched",
                uploaded_at=datetime.now(timezone.utc),
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            assert doc.status == DocumentStatus.UPLOADED
            assert doc.archived_at is None


@pytest.mark.asyncio
async def test_document_transition_uploaded_to_matched() -> None:
    """uploaded → matched (合法)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            doc = Document(
                organization_id=s["organization_id"],
                shipment_id=s["id"],
                filename="test.pdf", file_path="/tmp/test.pdf",
                file_hash="test_hash_002",
                mime_type="application/pdf", file_size=1024,
                source="manual_upload", doc_type=DocumentType.SO,
                ocr_status="pending", parse_status="unmatched",
                uploaded_at=datetime.now(timezone.utc),
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            doc_id = doc.id

        result = await _post(c, f"/api/v2/documents/{doc_id}/transition", {
            "to": "matched",
            "reason": "已 OCR 完成并匹配到 shipment",
        }, headers={"X-User-Id": "u-zhang", "X-User-Name": "operator.zhang"})

        assert result["status"] == "matched"
        assert result["archived_at"] is None  # 还没归档


@pytest.mark.asyncio
async def test_document_transition_to_archived_fills_archived_at() -> None:
    """any → archived, 自动填 archived_at + archived_by"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            doc = Document(
                organization_id=s["organization_id"],
                shipment_id=s["id"],
                filename="old.pdf", file_path="/tmp/old.pdf",
                file_hash="test_hash_archived",
                mime_type="application/pdf", file_size=1024,
                source="manual_upload", doc_type=DocumentType.SO,
                ocr_status="pending", parse_status="unmatched",
                uploaded_at=datetime.now(timezone.utc),
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            doc_id = doc.id

        result = await _post(c, f"/api/v2/documents/{doc_id}/transition", {
            "to": "archived",
            "reason": "业务结案, 归档文件",
        }, headers={"X-User-Id": "u-zhang", "X-User-Name": "operator.zhang"})

        assert result["status"] == "archived"
        assert result["archived_at"] is not None
        assert result["archived_by"] == "u-zhang"


@pytest.mark.asyncio
async def test_document_invalid_transition_blocked() -> None:
    """matched → uploaded (非法)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            doc = Document(
                organization_id=s["organization_id"],
                shipment_id=s["id"],
                filename="test.pdf", file_path="/tmp/test.pdf",
                file_hash="test_hash_003",
                mime_type="application/pdf", file_size=1024,
                source="manual_upload", doc_type=DocumentType.SO,
                ocr_status="pending", parse_status="unmatched",
                uploaded_at=datetime.now(timezone.utc),
                status=DocumentStatus.MATCHED,
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            doc_id = doc.id

        r = await c.post(f"/api/v2/documents/{doc_id}/transition", json={
            "to": "uploaded",
            "reason": "测试非法转换",
        })
        assert r.status_code == 400
        assert "invalid transition" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_document_transition_archived_terminal() -> None:
    """archived 是终态, 不能转出"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            doc = Document(
                organization_id=s["organization_id"],
                shipment_id=s["id"],
                filename="test.pdf", file_path="/tmp/test.pdf",
                file_hash="test_hash_004",
                mime_type="application/pdf", file_size=1024,
                source="manual_upload", doc_type=DocumentType.SO,
                ocr_status="pending", parse_status="unmatched",
                uploaded_at=datetime.now(timezone.utc),
                status=DocumentStatus.ARCHIVED,
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            doc_id = doc.id

        # 尝试转出 (任意状态都非法)
        r = await c.post(f"/api/v2/documents/{doc_id}/transition", json={
            "to": "uploaded",
            "reason": "尝试解档, 应该被状态机拒绝",
        })
        assert r.status_code == 400


# ========== Bill v0.5 ==========


@pytest.mark.asyncio
async def test_create_bill_v5() -> None:
    """POST /api/v2/bills/ 创建 Bill v0.5"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        bill = await _post(c, "/api/v2/bills/", {
            "bill_no": "B-V5-0001",
            "bill_type": "receivable",
            "bill_kind": "ocean_freight",
            "shipment_id": s["id"],
            "seller_name": "COSCO Shipping",
            "buyer_name": "ACME Corp",
            "currency": "USD",
            "total_amount": 1500.00,
            "tax_amount": 0.00,
            "amount_excl_tax": 1500.00,
            "due_at": "2026-09-01T00:00:00+00:00",
            "remark": "海运费 USD 1500",
        })
        assert bill["bill_no"] == "B-V5-0001"
        assert bill["status"] == "uploaded"  # 默认
        assert bill["total_amount"] == 1500.00
        assert bill["shipment_id"] == s["id"]


@pytest.mark.asyncio
async def test_list_bills_filter_by_shipment() -> None:
    """GET /api/v2/bills/?shipment_id=... 过滤"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 3 个 bill
        for i in range(3):
            await _post(c, "/api/v2/bills/", {
                "bill_no": f"B-V5-{i:04d}", "shipment_id": s["id"],
                "total_amount": 100.0 * (i + 1),
            })
        # 1 个其他 shipment 的 bill
        s2 = await _post(c, "/api/v2/shipments/", {
            "pol": "CNNGB", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "Y",
        })
        await _post(c, "/api/v2/bills/", {
            "bill_no": "B-V5-OTHER", "shipment_id": s2["id"], "total_amount": 999.0,
        })
        r = await c.get(f"/api/v2/bills/?shipment_id={s['id']}")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 3
        for it in items:
            assert it["shipment_id"] == s["id"]


@pytest.mark.asyncio
async def test_bill_state_machine_full_path() -> None:
    """Bill 7 态转换全跑通: uploaded → ocr_processing → ocr_done → confirmed → paid"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        bill = await _post(c, "/api/v2/bills/", {
            "bill_no": "B-V5-FULLPATH", "shipment_id": s["id"], "total_amount": 2000.0,
        })
        bill_id = bill["id"]

        # uploaded → ocr_processing
        r = await _post(c, f"/api/v2/bills/{bill_id}/transition", {
            "to": "ocr_processing", "reason": "OCR 排队",
        })
        assert r["status"] == "ocr_processing"

        # ocr_processing → ocr_done
        r = await _post(c, f"/api/v2/bills/{bill_id}/transition", {
            "to": "ocr_done", "reason": "OCR 识别完成",
        })
        assert r["status"] == "ocr_done"

        # ocr_done → confirmed
        r = await _post(c, f"/api/v2/bills/{bill_id}/transition", {
            "to": "confirmed", "reason": "财务确认入账",
        })
        assert r["status"] == "confirmed"

        # confirmed → paid
        r = await _post(c, f"/api/v2/bills/{bill_id}/transition", {
            "to": "paid", "reason": "客户已付款, 银行到账",
        }, headers={"X-User-Id": "u-finance", "X-User-Name": "finance.wang"})
        assert r["status"] == "paid"
        assert r["paid_at"] is not None

        # paid 是终态, 不能改
        r2 = await c.patch(f"/api/v2/bills/{bill_id}", json={"total_amount": 999.0})
        assert r2.status_code == 400


@pytest.mark.asyncio
async def test_bill_invalid_transition_blocked() -> None:
    """uploaded → paid (跳过中间, 非法)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        bill = await _post(c, "/api/v2/bills/", {
            "bill_no": "B-V5-INVALID", "shipment_id": s["id"], "total_amount": 100.0,
        })
        r = await c.post(f"/api/v2/bills/{bill['id']}/transition", json={
            "to": "paid", "reason": "跳过状态非法转换",
        })
        assert r.status_code == 400
        assert "invalid transition" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bill_transition_audit_log() -> None:
    """Bill 状态转换写 audit log"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        bill = await _post(c, "/api/v2/bills/", {
            "bill_no": "B-V5-AUDIT", "shipment_id": s["id"], "total_amount": 500.0,
        }, headers={"X-User-Id": "u-init", "X-User-Name": "init.user"})
        await _post(c, f"/api/v2/bills/{bill['id']}/transition", {
            "to": "ocr_processing", "reason": "触发 OCR",
        }, headers={"X-User-Id": "u-finance", "X-User-Name": "finance.wang"})

        r = await c.get(f"/api/v2/audit-logs/?entity_type=bill&entity_id={bill['id']}")
        assert r.status_code == 200
        logs = r.json()
        actions = [l["action"] for l in logs]
        assert "create" in actions
        assert "update" in actions
        # update log 应有 status 转换
        update_log = next(l for l in logs if l["action"] == "update")
        assert "status" in update_log["field_changes"]
        assert update_log["field_changes"]["status"]["old"] == "uploaded"
        assert update_log["field_changes"]["status"]["new"] == "ocr_processing"


# ========== Migration: bills 现在迁到 bills_v5 (不再 skipped) ==========


@pytest.mark.asyncio
async def test_migrate_bills_to_v5_not_skipped() -> None:
    """阶段 1.5.5 补完: bills 迁到 bills_v5 (不再 skipped)"""
    from app.models.agent import Agent
    from app.models.bill import Bill, BillKind as V4BillKind, BillStatus as V4BillStatus
    from app.models.booking import Booking, BookingStatus
    from app.services.migration import run_migration

    async with AsyncSessionLocal() as db:
        # Seed v0.4: 1 agent + 1 booking + 1 bill
        a = Agent(name="COSCO Test", booking_email="test@cosco.example", is_active=True)
        db.add(a)
        await db.flush()
        b = Booking(
            booking_no="V04-TEST-0001", pol="CNSHA", pod="USLAX",
            etd=datetime(2026, 8, 22, tzinfo=timezone.utc),
            eta=datetime(2026, 9, 8, tzinfo=timezone.utc),
            container_type="40HQ", container_count=1, commodity="X",
            customer_name="ACME", carrier="COSCO", agent_id=a.id,
            status=BookingStatus.CONFIRMED,
        )
        db.add(b)
        await db.flush()
        bill = Bill(
            booking_id=b.id, bill_no="B-V4-TEST", total_amount=1500.0,
            currency="USD", status=V4BillStatus.PAID, bill_kind=V4BillKind.OCEAN_FREIGHT,
        )
        db.add(bill)
        await db.commit()

        # 跑迁移
        result = await run_migration(db)
        assert result["bills"] == 1

        # 验证 bills_v5 表有 1 行
        bills_v5 = (await db.execute(select(BillV5))).scalars().all()
        assert len(bills_v5) == 1
        bv5 = bills_v5[0]
        assert bv5.bill_no == "B-V4-TEST"
        assert bv5.total_amount == 1500.0
        assert bv5.currency == "USD"
        assert bv5.status == BillStatus.PAID
        assert bv5.bill_kind == BillKind.OCEAN_FREIGHT
        assert bv5.shipment_id is not None  # 关联到 v0.5 shipment
        assert bv5.bill_type == BillType.RECEIVABLE  # v0.4 默认

        # legacy map 应该有 bill → bill (不再 skipped)
        bill_maps = (await db.execute(
            select(LegacyEntityMap).where(
                LegacyEntityMap.v04_type == "bill",
                LegacyEntityMap.v05_type == "bill",
            )
        )).scalars().all()
        assert len(bill_maps) == 1
        assert bill_maps[0].v05_id == bv5.id
