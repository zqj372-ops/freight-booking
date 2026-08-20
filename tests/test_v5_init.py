"""v0.5 初始化测试 - v0.4/v0.5 API 监控 + v1 只读守卫 + migration status"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.middleware import api_stats
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
    # 重置 APIStats singleton (避免测试间互相影响)
    api_stats.by_endpoint.clear()
    api_stats.v1_total = 0
    api_stats.v2_total = 0
    api_stats.other_total = 0
    yield


async def _get(client, path):
    r = await client.get(path)
    return r


# ========== V1ReadOnlyMiddleware 守卫 ==========


@pytest.mark.asyncio
async def test_v1_get_allowed() -> None:
    """v0.4 GET 仍可用 (兼容历史数据)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/agents/")
        # 200 (list 返空 list) 或 404 (路由不存在) 都行, 关键是 NOT 405/410
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_v1_post_returns_410_gone() -> None:
    """v0.4 POST → 410 Gone (deprecated)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/bookings/", json={"pol": "X", "pod": "Y"})
        assert r.status_code == 410
        assert r.headers.get("X-API-Deprecated") == "v0.4"
        assert r.headers.get("X-API-Use-Instead") == "v0.5"
        assert "v0.4 API deprecated" in r.json()["detail"]


@pytest.mark.asyncio
async def test_v1_patch_returns_410_gone() -> None:
    """v0.4 PATCH → 410"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch("/api/v1/agents/abc", json={"name": "X"})
        assert r.status_code == 410


@pytest.mark.asyncio
async def test_v1_delete_returns_410_gone() -> None:
    """v0.4 DELETE → 410"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete("/api/v1/bookings/abc")
        assert r.status_code == 410


@pytest.mark.asyncio
async def test_v2_endpoint_not_affected_by_v1_guard() -> None:
    """v0.5 POST 正常, 不被 v1 守卫拦截"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        assert r.status_code == 201
        assert "X-API-Deprecated" not in r.headers


# ========== APIStatsMiddleware 监控 ==========


@pytest.mark.asyncio
async def test_api_stats_records_v1_and_v2_calls() -> None:
    """middleware 记录 v1 + v2 调用, 区分版本"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 调 v1
        await c.get("/api/v1/agents/")
        # 调 v2
        await c.get("/api/v2/shipments/")
        await c.get("/api/v2/dashboard/")

    # 查 api-stats
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/migration/api-stats")
        assert r.status_code == 200
        data = r.json()

    assert data["v1_total"] >= 1
    assert data["v2_total"] >= 2  # shipments + dashboard
    total = data["total"]
    assert total >= 3
    # 比例对
    assert data["v1_pct"] + data["v2_pct"] + (data["other_total"] / total if total > 0 else 0) <= 1.0


@pytest.mark.asyncio
async def test_api_stats_by_endpoint_breakdown() -> None:
    """by_endpoint 列出每个 method+path 组合的 count + avg_ms"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.get("/api/v2/shipments/")
        await c.get("/api/v2/shipments/")
        await c.get("/api/v2/dashboard/")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/migration/api-stats")
        data = r.json()

    by_ep = data["by_endpoint"]
    # shipments 出现 2 次
    assert "GET:/api/v2/shipments" in by_ep
    assert by_ep["GET:/api/v2/shipments"]["count"] == 2
    assert by_ep["GET:/api/v2/shipments"]["version"] == "v2"
    assert by_ep["GET:/api/v2/shipments"]["avg_ms"] > 0


@pytest.mark.asyncio
async def test_api_stats_records_errors() -> None:
    """4xx 5xx 调用记 error_count"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.get("/api/v2/shipments/nonexistent-id-12345")  # 404

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/migration/api-stats")
        data = r.json()

    by_ep = data["by_endpoint"]
    # /api/v2/shipments/{id} 用 path prefix /api/v2/shipments
    assert "GET:/api/v2/shipments" in by_ep
    shipments_stat = by_ep["GET:/api/v2/shipments"]
    assert shipments_stat["error_count"] >= 1


@pytest.mark.asyncio
async def test_api_stats_response_header_x_api_version() -> None:
    """每个响应带 X-API-Version header"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.get("/api/v1/agents/")
        r2 = await c.get("/api/v2/shipments/")
        r3 = await c.get("/health")
    assert r1.headers.get("X-API-Version") == "v1"
    assert r2.headers.get("X-API-Version") == "v2"
    assert r3.headers.get("X-API-Version") == "other"
    # response time
    assert "X-Response-Time-Ms" in r2.headers


# ========== GET /api/v2/migration/status ==========


@pytest.mark.asyncio
async def test_migration_status_initial() -> None:
    """空 DB → migration status 返 0"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/migration/status")
        assert r.status_code == 200
        data = r.json()
        assert "organization_id" in data
        assert "v0.4_counts" in data
        assert "v0.5_counts" in data
        assert "legacy_map_by_v04_type" in data
        assert "legacy_map_by_v05_type" in data
        assert "migration_completeness" in data
        # 空 DB (除 bootstrap organization): 大部分 v0.5 表 0, organizations = 1
        assert data["v0.5_counts"]["organizations"] == 1
        assert data["v0.5_counts"]["shipments"] == 0
        assert data["v0.5_counts"]["partners"] == 0


@pytest.mark.asyncio
async def test_migration_status_after_seed_migrate() -> None:
    """seed_and_migrate 后, status 显示 v0.4 + v0.5 + legacy map 统计"""
    from app.models.agent import Agent
    from app.models.booking import Booking, BookingStatus
    from app.services.migration import run_migration

    # Seed 1 个 v0.4 booking
    async with AsyncSessionLocal() as db:
        a = Agent(name="Test Agent", booking_email="test@x.example", is_active=True)
        db.add(a)
        await db.flush()
        b = Booking(
            booking_no="V04-INIT-0001", pol="CNSHA", pod="USLAX",
            etd=datetime(2026, 8, 22, tzinfo=timezone.utc),
            eta=datetime(2026, 9, 8, tzinfo=timezone.utc),
            container_type="40HQ", container_count=1, commodity="X",
            customer_name="Test", carrier="COSCO", agent_id=a.id,
            status=BookingStatus.CONFIRMED,
        )
        db.add(b)
        await db.commit()
        await run_migration(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/migration/status")
        data = r.json()

    # v0.4 表计数
    assert data["v0.4_counts"]["agents"] >= 1
    assert data["v0.4_counts"]["bookings"] >= 1
    # v0.5 至少 1 shipment + 1 partner + 1 booking map
    assert data["v0.5_counts"]["shipments"] >= 1
    assert data["v0.5_counts"]["partners"] >= 1
    assert data["v0.5_counts"]["booking_confirmations"] >= 0
    # legacy map
    assert data["legacy_map_by_v04_type"].get("agent", 0) >= 1
    assert data["legacy_map_by_v04_type"].get("booking", 0) >= 1
    # completeness
    booking_complete = data["migration_completeness"]["booking"]
    assert booking_complete["total"] >= 1
    assert booking_complete["mapped"] >= 1
    assert booking_complete["completeness"] == 1.0
