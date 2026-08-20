"""v0.5 阶段 1.5.1 测试 - Shipment 8 业务阶段 + 触发字段"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import AsyncSessionLocal, Base, engine
from app.main import app


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


async def _post(client, path, json=None):
    r = await client.post(path, json=json or {})
    assert r.status_code in (200, 201), f"{path}: {r.status_code} {r.text}"
    return r.json()


@pytest.mark.asyncio
async def test_shipment_create_with_trigger_fields() -> None:
    """建业务单时, 11 触发字段 + customer_name 都接受"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN",
            "target_etd": "2026-09-15",
            "commodity": "ELECTRONIC",
            "customer_name": "ACME Corp",  # 新字段
        })
        assert s["customer_name"] == "ACME Corp"
        # 11 触发字段 nullable, 暂时全 None
        assert s["booking_request_sent_at"] is None
        assert s["so_received_at"] is None
        assert s["sealed_at"] is None
        assert s["cy_cutoff_at"] is None


@pytest.mark.asyncio
async def test_business_phase_default_is_build() -> None:
    """新建业务单没有 milestone, business_phase=1 (建业务)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        r = await c.get(f"/api/v2/workflow/shipments/{s['id']}/business-phase")
        assert r.status_code == 200
        data = r.json()
        assert data["phase"] == 1
        assert data["phase_label"] == "建业务"
        assert data["color"] in ("in_progress", "not_started")
        assert data["progress"] == 0.12  # 1/8 ≈ 0.12
        assert data["milestone_count"] == 0


@pytest.mark.asyncio
async def test_business_phase_advances_on_milestone() -> None:
    """录 milestone 后, business_phase 推进"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 录 booking_request_sent → phase=2
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/milestones", json={
            "code": "booking_request_sent",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })
        r = await c.get(f"/api/v2/workflow/shipments/{s['id']}/business-phase")
        assert r.json()["phase"] == 2
        assert r.json()["phase_label"] == "发订舱"

        # 录 booking_confirmation_accepted → phase=3
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/milestones", json={
            "code": "booking_confirmation_accepted",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })
        r = await c.get(f"/api/v2/workflow/shipments/{s['id']}/business-phase")
        assert r.json()["phase"] == 3
        assert r.json()["phase_label"] == "收/核 SO"

        # 录 departed → phase=7
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/milestones", json={
            "code": "departed",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })
        r = await c.get(f"/api/v2/workflow/shipments/{s['id']}/business-phase")
        assert r.json()["phase"] == 7
        assert r.json()["phase_label"] == "开船到港"
        assert r.json()["progress"] == 0.88  # 7/8

        # 录 empty_returned → phase=8
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/milestones", json={
            "code": "empty_returned",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })
        r = await c.get(f"/api/v2/workflow/shipments/{s['id']}/business-phase")
        assert r.json()["phase"] == 8
        assert r.json()["phase_label"] == "结案还柜"
        assert r.json()["progress"] == 1.0


@pytest.mark.asyncio
async def test_business_phase_color_overdue_when_exception_open() -> None:
    """有 open exception 时, 颜色 = overdue (红)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 开异常
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/exceptions", {
            "code": "so_mismatch", "severity": "warning",
        })
        r = await c.get(f"/api/v2/workflow/shipments/{s['id']}/business-phase")
        assert r.json()["color"] == "overdue"
        assert r.json()["has_open_exception"] is True


@pytest.mark.asyncio
async def test_business_phase_color_approaching_deadline() -> None:
    """4h 内 due_at → 颜色 = approaching_deadline (黄)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 建 task 截止 2h 后
        due_in_2h = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/tasks", {
            "code": "submit_si", "title": "提交 SI", "due_at": due_in_2h,
        })
        r = await c.get(f"/api/v2/workflow/shipments/{s['id']}/business-phase")
        assert r.json()["color"] == "approaching_deadline"
        assert r.json()["next_due_at"] is not None
        assert r.json()["next_task_title"] == "提交 SI"


@pytest.mark.asyncio
async def test_business_phase_color_normal() -> None:
    """没异常, due_at > 4h → 颜色 = in_progress (蓝)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # task 截止 24h 后
        due_in_24h = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        await _post(c, f"/api/v2/workflow/shipments/{s['id']}/tasks", {
            "code": "submit_si", "title": "提交 SI", "due_at": due_in_24h,
        })
        r = await c.get(f"/api/v2/workflow/shipments/{s['id']}/business-phase")
        assert r.json()["color"] == "in_progress"


@pytest.mark.asyncio
async def test_derive_business_phase_service() -> None:
    """直接测 service 函数 (不通过 API)"""
    from app.models._base import BusinessPhase
    from app.models.milestone import Milestone, MilestoneCode, MilestoneSource
    from app.services.workflow import (
        derive_business_phase,
        derive_phase_progress,
        PHASE_LABELS,
    )
    # 空 milestones
    assert derive_business_phase([]) == BusinessPhase.BUILD
    assert derive_phase_progress([]) == 0.12

    # 1 个 milestone
    ms_booking = [Milestone(code=MilestoneCode.BOOKING_REQUEST_SENT,
                          occurred_at=datetime.now(timezone.utc),
                          recorded_at=datetime.now(timezone.utc),
                          source=MilestoneSource.MANUAL)]
    assert derive_business_phase(ms_booking) == BusinessPhase.BOOKING
    assert PHASE_LABELS[BusinessPhase.BOOKING] == "发订舱"

    # 多 milestone 取最高
    ms_full = ms_booking + [
        Milestone(code=MilestoneCode.BOOKING_CONFIRMATION_ACCEPTED,
                  occurred_at=datetime.now(timezone.utc),
                  recorded_at=datetime.now(timezone.utc),
                  source=MilestoneSource.MANUAL),
        Milestone(code=MilestoneCode.CONTAINER_PICKED_UP,
                  occurred_at=datetime.now(timezone.utc),
                  recorded_at=datetime.now(timezone.utc),
                  source=MilestoneSource.MANUAL),
    ]
    assert derive_business_phase(ms_full) == BusinessPhase.PICKUP_LOAD
