"""v0.5 阶段 1.5.4 测试 - 主列表 12 字段 + dashboard 4 卡片 + document-checklist"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.task import Task, TaskCode, TaskStatus


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


# ========== 1.5.4a: 主列表 12 字段 ==========


@pytest.mark.asyncio
async def test_list_shipments_returns_12_fields() -> None:
    """GET /api/v2/shipments/ 返回 12 字段 (ShipmentListItem)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSZX", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "ELECTRONIC",
            "operator_user_name": "小周",
        })
        # 通过 milestone 推进 phase 到 2 (booking_request_sent)
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/milestones", json={
            "code": "booking_request_sent",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })

        r = await c.get("/api/v2/shipments/")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        item = items[0]
        # 12 字段
        assert "job_no" in item
        assert "route_summary" in item
        assert "carrier_partner" in item
        assert "vessel_voyage" in item
        assert "current_etd" in item
        assert "current_eta" in item
        assert "business_phase" in item
        assert "business_phase_label" in item
        assert "business_phase_color" in item
        assert "next_action" in item
        assert "next_due_at" in item
        assert "countdown_hours" in item
        assert "next_action_priority" in item
        assert "operator_user_name" in item
        assert "exception_label" in item
        assert "progress" in item
        # 字段值
        assert item["job_no"] == s["job_no"]
        assert "CNSZX" in item["route_summary"]
        assert "CAVAN" in item["route_summary"]
        assert "1×40HQ" in item["route_summary"]
        assert item["business_phase"] == 2  # booking_request_sent → phase 2
        assert item["business_phase_label"] == "发订舱"
        assert item["operator_user_name"] == "小周"
        assert item["exception_label"] == "—"
        assert item["progress"] >= 0.12


@pytest.mark.asyncio
async def test_list_item_advances_phase_by_milestone() -> None:
    """主列表 phase 随 milestone 推进"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 录 booking_request_sent + booking_confirmation_accepted
        for code in ["booking_request_sent", "booking_confirmation_accepted"]:
            await _post(c, f"/api/v2/workflow/shipments/{s['id']}/milestones", json={
                "code": code,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            })
        r = await c.get("/api/v2/shipments/")
        item = r.json()[0]
        assert item["business_phase"] == 3  # 收/核 SO
        assert item["business_phase_label"] == "收/核 SO"
        assert item["progress"] == 0.38  # 3/8


@pytest.mark.asyncio
async def test_list_item_exception_label_urgent() -> None:
    """open exception → exception_label = "重要" / "紧急" """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 1 个 warning exception
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/exceptions", {
            "code": "so_mismatch", "severity": "warning",
        })
        r = await c.get("/api/v2/shipments/")
        item = r.json()[0]
        assert item["exception_label"] in ("重要", "一般")  # warning + 1 个
        # 颜色 overdue
        assert item["business_phase_color"] == "overdue"


# ========== 1.5.4b: dashboard 4 卡片 ==========


@pytest.mark.asyncio
async def test_dashboard_empty_initial() -> None:
    """空 DB → 4 卡片全 0"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/dashboard/")
        assert r.status_code == 200
        stats = r.json()
        assert stats["overdue_tasks"] == 0
        assert stats["due_today"] == 0
        assert stats["awaiting_so"] == 0
        assert stats["arriving_within_7d"] == 0


@pytest.mark.asyncio
async def test_dashboard_overdue_count() -> None:
    """建任务 (过去 due) → overdue_tasks 计数"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 直接建 1 个 overdue task (用 workflow endpoint)
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/tasks", {
            "code": "submit_si", "title": "测试 SI", "due_at": past,
        })
        r = await c.get("/api/v2/dashboard/")
        stats = r.json()
        assert stats["overdue_tasks"] >= 1
        assert len(stats["overdue_tasks_top"]) >= 1
        top = stats["overdue_tasks_top"][0]
        assert top["title"] == "测试 SI"
        assert top["job_no"] == s["job_no"]


@pytest.mark.asyncio
async def test_dashboard_awaiting_so() -> None:
    """booking_request_sent_at 已设 + so_received_at 未设 → awaiting_so >= 1"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        await _patch(c, f"/api/v2/shipments/{s['id']}/events", {
            "booking_request_sent_at": datetime.now(timezone.utc).isoformat(),
        })
        r = await c.get("/api/v2/dashboard/")
        stats = r.json()
        assert stats["awaiting_so"] >= 1


@pytest.mark.asyncio
async def test_dashboard_arriving_within_7d() -> None:
    """eta 在未来 7 天内 → arriving_within_7d >= 1"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        from datetime import date
        # 7 日内 ETA: 直接通过 BC 设 — 简化: 走 PATCH /shipment
        # 实际: v0.5 中 eta 通过 BC 接受时设, 但 PATCH /shipment/{id} 也接受 eta
        eta = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        await _patch(c, f"/api/v2/shipments/{s['id']}", {
            "eta": eta,
        })
        r = await c.get("/api/v2/dashboard/")
        stats = r.json()
        assert stats["arriving_within_7d"] >= 1


@pytest.mark.asyncio
async def test_dashboard_due_today() -> None:
    """due_at 今日 → due_today >= 1"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 4h 后 (肯定今日)
        due_4h = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/tasks", {
            "code": "submit_si", "title": "今日到期 SI", "due_at": due_4h,
        })
        r = await c.get("/api/v2/dashboard/")
        stats = r.json()
        assert stats["due_today"] >= 1
        assert any(t["title"] == "今日到期 SI" for t in stats["due_today_top"])


# ========== 1.5.4c: document-checklist ==========


@pytest.mark.asyncio
async def test_document_checklist_initial_all_missing() -> None:
    """新建业务单, 8 类文件全 missing"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        r = await c.get(f"/api/v2/shipments/{s['id']}/document-checklist")
        assert r.status_code == 200
        cl = r.json()
        codes = {i["code"]: i for i in cl["items"]}
        # 8 类都有
        assert "so" in codes
        assert "si" in codes
        assert "vgm" in codes
        assert "customs" in codes
        assert "bl_draft" in codes
        assert "bl_final" in codes
        assert "emf" in codes
        assert "an" in codes
        assert "load_plan" in codes
        # 全 missing / not_applicable
        for code, item in codes.items():
            if code in ("an", "load_plan"):
                # not applicable? 实际: 我们的实现是 expected=1 + count=0 → missing
                # 但 v0.5 不强制 AN/Load Plan
                assert item["status"] in ("missing", "not_applicable")
        # total_completion: 0
        assert cl["total_completed"] == 0
        assert cl["completion"] == 0.0


@pytest.mark.asyncio
async def test_document_checklist_so_completed() -> None:
    """录 booking_confirmation_accepted milestone → SO 算齐套 (1/1)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 接受 BC (建 current) — 通过 BC accept endpoint
        # v0.5 简化: 直接建 BC + accept
        from app.database import AsyncSessionLocal
        from app.models.booking_confirmation import (
            BookingConfirmation, BookingConfirmationStatus,
        )
        async with AsyncSessionLocal() as db:
            bc = BookingConfirmation(
                organization_id=s["organization_id"],
                shipment_id=s["id"],
                version=1, is_current=True,
                status=BookingConfirmationStatus.ACCEPTED,
                so_no="SO-12345",
            )
            db.add(bc)
            await db.commit()

        r = await c.get(f"/api/v2/shipments/{s['id']}/document-checklist")
        cl = r.json()
        codes = {i["code"]: i for i in cl["items"]}
        assert codes["so"]["status"] == "completed"
        assert codes["so"]["count"] == 1
        # completion 至少 1/9 ≈ 0.11 (但 bl_final 仍 missing, 因为没 departed)
        assert cl["total_completed"] >= 1


@pytest.mark.asyncio
async def test_document_checklist_si_vgm_via_milestone() -> None:
    """录 si_submitted / vgm_submitted milestone → SI/VGM 算齐套"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        for code in ["si_submitted", "vgm_submitted", "customs_cleared"]:
            await _post(c, f"/api/v2/workflow/shipments/{s['id']}/milestones", json={
                "code": code,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            })
        r = await c.get(f"/api/v2/shipments/{s['id']}/document-checklist")
        cl = r.json()
        codes = {i["code"]: i for i in cl["items"]}
        assert codes["si"]["status"] == "completed"
        assert codes["vgm"]["status"] == "completed"
        assert codes["customs"]["status"] == "completed"


@pytest.mark.asyncio
async def test_document_checklist_bl_emf_after_departure() -> None:
    """录 departed milestone → BL final/EMF 算齐套 (但 expected 仍 1)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/milestones", json={
            "code": "departed",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })
        r = await c.get(f"/api/v2/shipments/{s['id']}/document-checklist")
        cl = r.json()
        codes = {i["code"]: i for i in cl["items"]}
        assert codes["bl_final"]["status"] == "completed"
        assert codes["emf"]["status"] == "completed"
