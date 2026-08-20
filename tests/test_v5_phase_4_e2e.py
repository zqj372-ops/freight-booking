"""v0.5 阶段 4 端到端 9 步验收测试

9 步完整业务链路:
  1. 建业务单 (POST /api/v2/shipments/)
  2. 发订舱 (PATCH /events booking_request_sent_at → fire BOOKING_REQUEST_SENT trigger)
  3. 收 SO (建 Document, 模拟 SO 入库)
  4. 接受 BC (建 BookingConfirmation, 触发 on_booking_confirmation_accepted → 建 4 task)
  5. 自动开 task (验证 task 已建, 包含 arrange_pickup / record_container_no / submit_si / submit_vgm)
  6. 提柜 (录 milestone container_picked_up, 触发 trigger)
  7. 装船 (录 milestone container_loaded, 触发 trigger)
  8. 提交 SI (录 milestone si_submitted + si_sent trigger)
  9. 开船 (录 milestone departed, 触发 trigger get_onboard_bl / get_emf)

每步断言:
- HTTP 200/201
- 关键字段 (business_phase / status / tasks / milestones)
- trigger 副作用 (新 task / 自动 close / state machine)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.booking_confirmation import BookingConfirmation
from app.models.document import Document
from app.models.legacy_entity_map import LegacyEntityMap
from app.models.milestone import Milestone, MilestoneCode
from app.models.task import Task, TaskCode, TaskStatus
from app.services.migration import run_migration


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


async def _seed_v04(db) -> None:
    """seed v0.4 测试数据: 1 个 draft 业务单候选 (POD 业务流)"""
    from app.models.agent import Agent
    from app.models.booking import Booking, BookingStatus

    a = Agent(name="COSCO E2E", code="E2E", booking_email="e2e@cosco.example", is_active=True)
    db.add(a)
    await db.flush()

    b = Booking(
        booking_no="E2E-0001", pol="CNSZX", pod="CAVAN",
        etd=datetime(2026, 9, 1, tzinfo=timezone.utc),
        eta=datetime(2026, 9, 20, tzinfo=timezone.utc),
        container_type="40HQ", container_count=1, commodity="E2E_TEST_GOODS",
        customer_name="E2E Corp", customer_ref="E2E-001",
        carrier="COSCO", agent_id=a.id, status=BookingStatus.DRAFT,
    )
    db.add(b)
    await db.commit()
    return b.id


# ========== 9 步端到端主测试 ==========


@pytest.mark.asyncio
async def test_e2e_9_steps_full_flow() -> None:
    """9 步端到端全跑通:
       建单 → 发订舱 → 收SO → 接受BC → 自动开task → 提柜 → 装船 → 提交SI → 开船
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # ====== Step 1: 建业务单 (从 v0.4 booking 迁过来) ======
        async with AsyncSessionLocal() as db:
            v04_booking_id = await _seed_v04(db)
            await db.commit()
            await run_migration(db)

        # 找到 v0.5 shipment (从 legacy map)
        async with AsyncSessionLocal() as db:
            m = (await db.execute(
                select(LegacyEntityMap).where(
                    LegacyEntityMap.v04_type == "booking",
                    LegacyEntityMap.v04_id == v04_booking_id,
                )
            )).scalar_one()
            v05_ship_id = m.v05_id

        # 验证: 主列表能查到
        r = await c.get("/api/v2/shipments/")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        # 验证 business-phase 默认 = 1 (建业务)
        r = await c.get(f"/api/v2/workflow/shipments/{v05_ship_id}/business-phase")
        assert r.json()["phase"] == 1
        assert r.json()["phase_label"] == "建业务"
        assert r.json()["milestone_count"] == 0

        # ====== Step 2: 发订舱 (PATCH events booking_request_sent_at) ======
        await _patch(c, f"/api/v2/shipments/{v05_ship_id}/events", {
            "booking_request_sent_at": datetime.now(timezone.utc).isoformat(),
        })

        # 验证: business-phase 推进到 2 (发订舱)
        r = await c.get(f"/api/v2/workflow/shipments/{v05_ship_id}/business-phase")
        assert r.json()["phase"] == 2
        assert r.json()["phase_label"] == "发订舱"

        # ====== Step 3: 收 SO (建 Document) ======
        # 模拟: 邮件 IMAP 收到 SO, 走 OCR, 系统建 Document + 等 confirm
        from app.models.document import DocumentType, DocumentSource, OcrStatus
        async with AsyncSessionLocal() as db:
            doc = Document(
                id=f"e2e_doc_001",
                organization_id=(await db.execute(select(LegacyEntityMap).where(
                    LegacyEntityMap.v04_type == "booking",
                    LegacyEntityMap.v04_id == v04_booking_id,
                ))).scalar_one().organization_id,
                shipment_id=v05_ship_id,
                filename="SO_E2E_001.pdf",
                file_path="/tmp/SO_E2E_001.pdf",
                file_hash="e2e_hash_001",
                mime_type="application/pdf",
                file_size=2048,
                source=DocumentSource.IMAP_ATTACHMENT,
                doc_type=DocumentType.SO,
                ocr_status=OcrStatus.DONE,
                ocr_text="SO 082E COSCO SHIPPING 2026-09-01 ETD CAVAN",
                ocr_confidence=0.95,
                parse_status="matched_booking",
                uploaded_at=datetime.now(timezone.utc),
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            so_doc_id = doc.id

        # 验证: document-checklist SO 1/1
        r = await c.get(f"/api/v2/shipments/{v05_ship_id}/document-checklist")
        cl = r.json()
        so_item = next(i for i in cl["items"] if i["code"] == "so")
        assert so_item["status"] == "completed"
        assert so_item["count"] == 1

        # ====== Step 4: 接受 BC (建 BookingConfirmation, 触发 on_booking_confirmation_accepted) ======
        from app.models.booking_confirmation import BookingConfirmationStatus
        from app.models.document import Document as Doc
        from datetime import date

        async with AsyncSessionLocal() as db:
            m = (await db.execute(
                select(LegacyEntityMap).where(
                    LegacyEntityMap.v04_type == "booking",
                    LegacyEntityMap.v04_id == v04_booking_id,
                )
            )).scalar_one()
            org_id = m.organization_id

            bc = BookingConfirmation(
                id="e2e_bc_001",
                organization_id=org_id,
                shipment_id=v05_ship_id,
                document_id=so_doc_id,
                version=1,
                is_current=True,
                status=BookingConfirmationStatus.ACCEPTED,
                so_no="SO-E2E-001",
                carrier="COSCO",
                vessel_name="COSCO SHIPPING",
                voyage_no="082E",
                pol="CNSZX",
                pod="CAVAN",
                etd=date(2026, 9, 1),
                eta=date(2026, 9, 20),
                si_cutoff_at=datetime(2026, 8, 31, 18, tzinfo=timezone.utc),
                vgm_cutoff_at=datetime(2026, 8, 31, 20, tzinfo=timezone.utc),
                cy_cutoff_at=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
                cy_open_at=datetime(2026, 8, 30, 8, tzinfo=timezone.utc),
                container_type="40HQ",
                container_count=1,
                accepted_at=datetime.now(timezone.utc),
            )
            db.add(bc)
            await db.commit()

            # 手动触发 on_booking_confirmation_accepted (生产环境: BC accept endpoint)
            from app.services.workflow import on_booking_confirmation_accepted
            await on_booking_confirmation_accepted(
                db, organization_id=org_id,
                shipment_id=v05_ship_id, booking_confirmation_id=bc.id,
            )
            await db.commit()

        # ====== Step 5: 验证 4 task 自动建 ======
        async with AsyncSessionLocal() as db:
            tasks = (await db.execute(
                select(Task).where(Task.shipment_id == v05_ship_id)
            )).scalars().all()

        task_codes = {t.code.value for t in tasks}
        assert TaskCode.ARRANGE_PICKUP.value in task_codes
        assert TaskCode.RECORD_CONTAINER_NO.value in task_codes
        assert TaskCode.SUBMIT_SI.value in task_codes
        assert TaskCode.SUBMIT_VGM.value in task_codes
        assert len(tasks) == 4
        for t in tasks:
            assert t.status == TaskStatus.PENDING
            assert t.due_at is not None  # 有 due_at (从 BC.si_cutoff_at 等推)

        # 验证: business-phase 推进到 3 (收/核 SO)
        r = await c.get(f"/api/v2/workflow/shipments/{v05_ship_id}/business-phase")
        assert r.json()["phase"] == 3
        assert r.json()["phase_label"] == "收/核 SO"

        # ====== Step 6: 提柜 (录 milestone container_picked_up) ======
        from app.models.milestone import MilestoneSource
        await _post(c, f"/api/v2/workflow/shipments/{v05_ship_id}/milestones", json={
            "code": "container_picked_up",
            "occurred_at": datetime(2026, 8, 21, 14, tzinfo=timezone.utc).isoformat(),
            "container_no": "COSU9999999",
            "source": "manual",
            "remark": "提柜完成",
        })

        # 验证: business-phase 推进到 4 (提柜装柜)
        r = await c.get(f"/api/v2/workflow/shipments/{v05_ship_id}/business-phase")
        assert r.json()["phase"] == 4
        assert r.json()["phase_label"] == "提柜装柜"

        # 验证: milestone 已存
        async with AsyncSessionLocal() as db:
            ms = (await db.execute(
                select(Milestone).where(Milestone.shipment_id == v05_ship_id)
            )).scalars().all()
        assert any(m.code == MilestoneCode.CONTAINER_PICKED_UP for m in ms)

        # ====== Step 7: 装船 (录 milestone container_loaded) ======
        await _post(c, f"/api/v2/workflow/shipments/{v05_ship_id}/milestones", json={
            "code": "container_loaded",
            "occurred_at": datetime(2026, 8, 22, 9, tzinfo=timezone.utc).isoformat(),
            "source": "manual",
        })

        # 验证: 仍在 phase 4 (提柜装柜)
        r = await c.get(f"/api/v2/workflow/shipments/{v05_ship_id}/business-phase")
        assert r.json()["phase"] == 4

        # ====== Step 8: 提交 SI (录 milestone si_submitted) ======
        await _post(c, f"/api/v2/workflow/shipments/{v05_ship_id}/milestones", json={
            "code": "si_submitted",
            "occurred_at": datetime(2026, 8, 22, 11, tzinfo=timezone.utc).isoformat(),
            "source": "manual",
        })

        # 验证: phase 推进到 5 (补料提单)
        r = await c.get(f"/api/v2/workflow/shipments/{v05_ship_id}/business-phase")
        assert r.json()["phase"] == 5
        assert r.json()["phase_label"] == "补料提单"

        # 验证: submit_si task 被 auto_close (auto_close_on=si_submitted)
        async with AsyncSessionLocal() as db:
            si_task = (await db.execute(
                select(Task).where(
                    Task.shipment_id == v05_ship_id,
                    Task.code == TaskCode.SUBMIT_SI,
                )
            )).scalar_one()
        assert si_task.status == TaskStatus.DONE

        # ====== Step 9: 开船 (录 milestone departed) ======
        await _post(c, f"/api/v2/workflow/shipments/{v05_ship_id}/milestones", json={
            "code": "departed",
            "occurred_at": datetime(2026, 9, 1, 23, tzinfo=timezone.utc).isoformat(),
            "vessel_name": "COSCO SHIPPING",
            "voyage_no": "082E",
            "source": "manual",
        })

        # 验证: phase 推进到 7 (开船到港)
        r = await c.get(f"/api/v2/workflow/shipments/{v05_ship_id}/business-phase")
        assert r.json()["phase"] == 7
        assert r.json()["phase_label"] == "开船到港"
        assert r.json()["milestone_count"] >= 4

        # 验证: departed 触发 get_onboard_bl + get_emf task 自动建
        async with AsyncSessionLocal() as db:
            late_tasks = (await db.execute(
                select(Task).where(Task.shipment_id == v05_ship_id)
            )).scalars().all()
        late_codes = {t.code.value for t in late_tasks}
        assert "get_onboard_bl" in late_codes
        assert "get_emf" in late_codes

        # 验证: 主列表返 + business_phase 是开船到港
        r = await c.get("/api/v2/shipments/")
        item = next(i for i in r.json() if i["id"] == v05_ship_id)
        assert item["business_phase_label"] == "开船到港"
        # next_action 是最近 due 的 open task (没要求是哪个, 验证有值即可)
        assert item["next_action"] not in ("", None)
        # 主列表进度 >= 7/8 = 0.875
        assert item["progress"] >= 0.85


# ========== 边界情况 ==========


@pytest.mark.asyncio
async def test_e2e_document_transition_through_upload() -> None:
    """Document upload → uploaded → matched → archived 状态机"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 建业务单
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 建 Document
        from app.database import AsyncSessionLocal
        from app.models.document import Document, DocumentType, DocumentSource
        async with AsyncSessionLocal() as db:
            doc = Document(
                id="e2e_doc_002",
                organization_id=s["organization_id"],
                shipment_id=s["id"],
                filename="test.pdf", file_path="/tmp/test.pdf",
                file_hash="e2e_hash_002",
                mime_type="application/pdf", file_size=1024,
                source=DocumentSource.MANUAL_UPLOAD,
                doc_type=DocumentType.SO,
                ocr_status="pending", parse_status="unmatched",
                uploaded_at=datetime.now(timezone.utc),
            )
            db.add(doc)
            await db.commit()

        # uploaded → matched
        r = await _post(c, f"/api/v2/documents/{doc.id}/transition", {
            "to": "matched", "reason": "已 OCR 完成并匹配到 shipment",
        })
        assert r["status"] == "matched"

        # matched → archived
        r = await _post(c, f"/api/v2/documents/{doc.id}/transition", {
            "to": "archived", "reason": "业务结案, 归档文件",
        }, headers={"X-User-Id": "u-arch", "X-User-Name": "archiver"})
        assert r["status"] == "archived"
        assert r["archived_at"] is not None
        assert r["archived_by"] == "u-arch"


@pytest.mark.asyncio
async def test_e2e_bill_state_machine() -> None:
    """Bill 7 态全跑通"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        bill = await _post(c, "/api/v2/bills/", {
            "bill_no": "B-E2E-001", "shipment_id": s["id"],
            "total_amount": 1500.0, "currency": "USD",
            "bill_type": "receivable", "bill_kind": "ocean_freight",
        })

        # uploaded → ocr_processing → ocr_done → confirmed → paid
        for to, reason in [
            ("ocr_processing", "OCR 排队"),
            ("ocr_done", "OCR 识别完成"),
            ("confirmed", "财务确认入账"),
            ("paid", "客户已付款"),
        ]:
            r = await _post(c, f"/api/v2/bills/{bill['id']}/transition", {
                "to": to, "reason": reason,
            })
            assert r["status"] == to

        # paid 终态, 不能 PATCH
        r = await c.patch(f"/api/v2/bills/{bill['id']}", json={"total_amount": 999.0})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_e2e_dashboard_reflects_real_state() -> None:
    """Dashboard 4 卡片反映真业务状态 (overdue_tasks / awaiting_so / etc)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 建业务单 + 设 booking_request_sent → awaiting_so 应 >= 1
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        await _patch(c, f"/api/v2/shipments/{s['id']}/events", {
            "booking_request_sent_at": datetime.now(timezone.utc).isoformat(),
        })

        r = await c.get("/api/v2/dashboard/")
        d = r.json()
        assert d["awaiting_so"] >= 1


@pytest.mark.asyncio
async def test_e2e_v0_4_api_blocked() -> None:
    """v0.4 API 写操作 → 410 Gone"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # v0.4 POST 应该被 V1ReadOnlyMiddleware 拦截
        r = await c.post("/api/v1/bookings/", json={"pol": "X", "pod": "Y"})
        assert r.status_code == 410
        assert "v0.4 API deprecated" in r.json()["detail"]

        # v0.4 GET 仍允许
        r = await c.get("/api/v1/agents/")
        # 200 (空 list) 或 404 都行, 关键是 NOT 410
        assert r.status_code in (200, 404)


@pytest.mark.asyncio
async def test_e2e_migration_status_complete() -> None:
    """v0.5 初始化后, migration status 显示 v0.5 表 + 完整度"""
    from app.models.agent import Agent
    from app.models.booking import Booking, BookingStatus

    async with AsyncSessionLocal() as db:
        # Seed 1 个 v0.4 booking
        a = Agent(name="MIG Agent", booking_email="mig@x.example", is_active=True)
        db.add(a)
        await db.flush()
        b = Booking(
            booking_no="MIG-0001", pol="CNSHA", pod="USLAX",
            etd=datetime(2026, 8, 22, tzinfo=timezone.utc),
            eta=datetime(2026, 9, 8, tzinfo=timezone.utc),
            container_type="40HQ", container_count=1, commodity="X",
            customer_name="Mig Corp", carrier="COSCO", agent_id=a.id,
            status=BookingStatus.CONFIRMED,
        )
        db.add(b)
        await db.commit()
        await run_migration(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/migration/status")
        d = r.json()

    # 验证 v0.4 计数
    assert d["v0.4_counts"]["agents"] >= 1
    assert d["v0.4_counts"]["bookings"] >= 1
    # v0.5 至少 1 shipment + 1 partner
    assert d["v0.5_counts"]["shipments"] >= 1
    assert d["v0.5_counts"]["partners"] >= 1
    # 完整度: agent/booking 都 1.0 (全迁完)
    assert d["migration_completeness"]["agent"]["completeness"] == 1.0
    assert d["migration_completeness"]["booking"]["completeness"] == 1.0
