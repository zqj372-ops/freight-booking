"""v0.6.3 头程时效 e2e 测试

覆盖:
1. 首次设 ETA (initial) → delta=0, 不建异常
2. 推后 < 3 天 → 不建异常
3. 推后 >= 3 天 → 自动建 ETA_DELAYED 异常 (>= 7 critical, 否则 warning)
4. 提前 (new < old) → 不建异常
5. ETA 历史列表
6. 头程看板 (含 in_transit / delayed / upcoming)
7. 手动触发 ETA 延误检测
8. ETA 已过 N 天未卸货 → ETA_PASSED_UNLOADED
9. ETA 已过 N 天未派送 (已卸货) → ETA_PASSED_DELIVERED
10. 404 / 400 边界
11. 异常自动 enqueue v0.6.1 AI 跟进
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.transit_time import EtaUpdate
from app.models.exception_update import ExceptionUpdate, ExceptionUpdateType
from app.models.milestone import Milestone, MilestoneCode
from app.models.operational_exception import (
    ExceptionCode,
    OperationalException,
    ExceptionStatus,
)
from app.models.shipment import Shipment, ShipmentStage


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


async def _make_shipment(c, eta: date | None = None, stage: str = "draft") -> str:
    body = {
        "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-08-25",
        "commodity": "X", "container_count": 1, "container_type": "40HQ",
    }
    s = await c.post("/api/v2/shipments/", json=body)
    assert s.status_code == 201
    sid = s.json()["id"]
    # 设 ETA (PATCH)
    if eta:
        r = await c.patch(f"/api/v2/shipments/{sid}", json={"eta": eta.isoformat()})
        assert r.status_code == 200
    # 改 stage (用于延误检测测试)
    if stage != "draft":
        async with AsyncSessionLocal() as db:
            ship = (await db.execute(select(Shipment).where(Shipment.id == sid))).scalar_one()
            ship.stage = ShipmentStage(stage)
            await db.commit()
    return sid


async def _add_milestone(shipment_id: str, code: MilestoneCode) -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        ms = Milestone(
            id=f"ms-{code.value}-{shipment_id[:8]}",
            organization_id="test",
            shipment_id=shipment_id,
            code=code,
            occurred_at=now,
            recorded_at=now,
        )
        db.add(ms)
        await db.commit()


# ========== 1. 首次设 ETA (initial) ==========


@pytest.mark.asyncio
async def test_first_eta_update_is_initial() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r = await c.post(f"/api/v2/shipments/{sid}/eta", json={
            "new_eta": "2026-09-15", "reason": "initial", "source": "manual",
        })
        assert r.status_code == 201
        j = r.json()
        assert j["delta_days"] == 0
        assert j["reason"] == "initial"
        assert j["triggered_exception_id"] is None


# ========== 2. 推后 < 3 天 → 不建异常 ==========


@pytest.mark.asyncio
async def test_delay_under_3d_no_exception() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-15", "reason": "initial"})
        r = await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-16", "reason": "vessel_delay"})
        assert r.status_code == 201
        assert r.json()["delta_days"] == 1
        assert r.json()["triggered_exception_id"] is None


# ========== 3. 推后 >= 3 天 → ETA_DELAYED ==========


@pytest.mark.asyncio
async def test_delay_3d_creates_exception() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-15", "reason": "initial"})
        r = await c.post(f"/api/v2/shipments/{sid}/eta", json={
            "new_eta": "2026-09-18", "reason": "port_delay", "change_reason": "LA 港拥堵",
        })
        assert r.status_code == 201
        j = r.json()
        assert j["delta_days"] == 3
        assert j["triggered_exception_id"] is not None
        # 验证异常在数据库
        async with AsyncSessionLocal() as db:
            ex = (await db.execute(
                select(OperationalException).where(OperationalException.id == j["triggered_exception_id"])
            )).scalar_one()
        assert ex.code == ExceptionCode.ETA_DELAYED
        assert ex.severity.value == "warning"  # 3-6 天 warning


@pytest.mark.asyncio
async def test_delay_7d_creates_critical_exception() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-15", "reason": "initial"})
        r = await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-25", "reason": "vessel_delay"})
        j = r.json()
        assert j["delta_days"] == 10
        assert j["triggered_exception_id"] is not None
        async with AsyncSessionLocal() as db:
            ex = (await db.execute(
                select(OperationalException).where(OperationalException.id == j["triggered_exception_id"])
            )).scalar_one()
        assert ex.severity.value == "critical"  # >= 7 天 critical


# ========== 4. 提前 → 不建异常 ==========


@pytest.mark.asyncio
async def test_earlier_eta_no_exception() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-15", "reason": "initial"})
        r = await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-12", "reason": "carrier_revise"})
        assert r.json()["delta_days"] == -3
        assert r.json()["triggered_exception_id"] is None


# ========== 5. ETA 历史列表 ==========


@pytest.mark.asyncio
async def test_eta_history() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        for i in range(3):
            r = await c.post(f"/api/v2/shipments/{sid}/eta", json={
                "new_eta": f"2026-09-{15 + i:02d}", "reason": "initial" if i == 0 else "vessel_delay",
            })
            assert r.status_code == 201
        r2 = await c.get(f"/api/v2/shipments/{sid}/eta/history")
        assert r2.status_code == 200
        assert len(r2.json()) == 3


# ========== 6. 头程看板 ==========


@pytest.mark.asyncio
async def test_transit_board() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 2 个 shipment: 1 scheduled, 1 in_transit
        s1 = await _make_shipment(c, eta=date(2026, 9, 15))
        s2 = await _make_shipment(c, eta=date(2026, 9, 20), stage="departed")
        await _add_milestone(s2, MilestoneCode.DEPARTED)

        r = await c.get("/api/v2/transit/board")
        assert r.status_code == 200
        j = r.json()
        assert j["total"] >= 2
        assert "scheduled" in j["by_status"]
        assert "departed_in_transit" in j["by_status"]


# ========== 7. 手动触发延误检测 (今天 ETA 已过未卸货) ==========


@pytest.mark.asyncio
async def test_manual_check_eta_delays_creates_unload_exception() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # shipment 已 DEPARTED, ETA 5 天前, 未卸货
        past_eta = date.today() - timedelta(days=5)
        sid = await _make_shipment(c, eta=past_eta, stage="departed")

        r = await c.post("/api/v2/transit/check-eta-delays")
        assert r.status_code == 200
        j = r.json()
        # 应至少 1 个 ETA_PASSED_UNLOADED
        assert j["new_exceptions_count"] >= 1
        async with AsyncSessionLocal() as db:
            ex = (await db.execute(
                select(OperationalException).where(OperationalException.shipment_id == sid)
            )).scalars().all()
        codes = {e.code for e in ex}
        assert ExceptionCode.ETA_PASSED_UNLOADED in codes


# ========== 8. ETA_PASSED_DELIVERED (已卸货, ETA 过 5 天未派送) ==========


@pytest.mark.asyncio
async def test_check_eta_delays_creates_deliver_exception() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        past_eta = date.today() - timedelta(days=10)
        sid = await _make_shipment(c, eta=past_eta, stage="departed")
        await _add_milestone(sid, MilestoneCode.DEPARTED)
        await _add_milestone(sid, MilestoneCode.ARRIVED_AT_POD)
        await _add_milestone(sid, MilestoneCode.CONTAINER_DISCHARGED)
        # 不加 DELIVERED

        r = await c.post("/api/v2/transit/check-eta-delays")
        assert r.status_code == 200
        async with AsyncSessionLocal() as db:
            exs = (await db.execute(
                select(OperationalException).where(OperationalException.shipment_id == sid)
            )).scalars().all()
        codes = {e.code for e in exs}
        assert ExceptionCode.ETA_PASSED_DELIVERED in codes


# ========== 9. 重复 ETA_DELAYED 不重复建 ==========


@pytest.mark.asyncio
async def test_eta_delayed_no_duplicate() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-15", "reason": "initial"})
        await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-20", "reason": "vessel_delay"})
        # 再次推后
        await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-25", "reason": "vessel_delay"})

        async with AsyncSessionLocal() as db:
            ex = (await db.execute(
                select(OperationalException).where(
                    OperationalException.shipment_id == sid,
                    OperationalException.code == ExceptionCode.ETA_DELAYED,
                    OperationalException.status == ExceptionStatus.OPEN,
                )
            )).scalars().all()
        # 应该只有 1 个 open 的 ETA_DELAYED
        assert len(ex) == 1


# ========== 10. 404 / 400 边界 ==========


@pytest.mark.asyncio
async def test_eta_update_404_for_missing_shipment() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v2/shipments/nonexistent/eta", json={"new_eta": "2026-09-15"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_eta_history_404_for_missing_shipment() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/shipments/nonexistent/eta/history")
        assert r.status_code == 404


# ========== 11. 异常自动 enqueue v0.6.1 AI 跟进 ==========


@pytest.mark.asyncio
async def test_eta_exception_triggers_ai_followup() -> None:
    """ETA_DELAYED 异常自动建 + 写 STATUS_CHANGE update (AI 跟进已启动)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-15", "reason": "initial"})
        await c.post(f"/api/v2/shipments/{sid}/eta", json={"new_eta": "2026-09-20", "reason": "vessel_delay"})

        async with AsyncSessionLocal() as db:
            ex = (await db.execute(
                select(OperationalException).where(
                    OperationalException.shipment_id == sid,
                    OperationalException.code == ExceptionCode.ETA_DELAYED,
                )
            )).scalar_one()
            updates = (await db.execute(
                select(ExceptionUpdate).where(ExceptionUpdate.exception_id == ex.id)
            )).scalars().all()
        # on_exception_created 写 STATUS_CHANGE update
        assert any(u.update_type == ExceptionUpdateType.STATUS_CHANGE for u in updates)
