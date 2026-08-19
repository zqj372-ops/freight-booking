"""Smoke test - 不依赖 OCR, 跑通最小流程"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import init_db
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.database import Base, engine, AsyncSessionLocal
    from app import models  # noqa: F401

    # 先清表 (开发测试用, 生产别这么干)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    from app.utils.bootstrap import _seed
    async with AsyncSessionLocal() as s:
        await _seed(s)
    yield
    # 不清表, 方便调试; CI 加 cleanup


@pytest.mark.asyncio
async def test_health() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_create_and_list_agent() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/v1/agents/",
            json={"name": "测试代理", "code": "TEST", "booking_email": "test@example.com"},
        )
        assert r.status_code == 201
        agent_id = r.json()["id"]

        r = await c.get("/api/v1/agents/")
        assert r.status_code == 200
        assert any(a["id"] == agent_id for a in r.json())


@pytest.mark.asyncio
async def test_list_email_templates() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/emails/templates")
        assert r.status_code == 200
        codes = [t["code"] for t in r.json()]
        assert "booking_request" in codes


@pytest.mark.asyncio
async def test_so_parser_basic() -> None:
    """SO 文本解析 - 规则覆盖"""
    from app.services.so_parser import parse_so_text

    text = """
    MAERSK LINE Booking Confirmation

    Booking No: MAE123456789
    Vessel: MAERSK HONG KONG V.345E
    Port of Loading: SHANGHAI (CNSHA)
    Port of Discharge: LOS ANGELES (USLAX)
    ETD: 2026-09-15
    ETA: 2026-10-05

    Container: 2 x 40HQ
    Commodity: ELECTRONIC PARTS
    """
    fields = parse_so_text(text)
    assert fields["carrier"] == "MAERSK"
    assert fields["so_number"] == "MAE123456789"
    assert fields["vessel_name"] is not None
    assert "CNSHA" in (fields["pol"] or "").upper() or "SHANGHAI" in (fields["pol"] or "").upper()
    assert fields["container_type"] == "40HQ"
    assert fields["container_count"] == 2


@pytest.mark.asyncio
async def test_create_booking_and_state_machine() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 先建一个 agent
        r = await c.post(
            "/api/v1/agents/",
            json={"name": "中转代理", "booking_email": "booking@agent.com"},
        )
        agent_id = r.json()["id"]

        # 建订舱
        r = await c.post(
            "/api/v1/bookings/",
            json={
                "carrier": "MAERSK",
                "pol": "CNSHA",
                "pod": "USLAX",
                "agent_id": agent_id,
                "container_type": "40HQ",
                "container_count": 1,
            },
        )
        assert r.status_code == 201
        booking_id = r.json()["id"]
        assert r.json()["status"] == "draft"

        # 状态机: draft -> submitted
        r = await c.patch(
            f"/api/v1/bookings/{booking_id}",
            json={"status": "submitted"},
        )
        assert r.status_code == 200

        # 状态机: submitted -> draft (非法跳回 cancelled 不允许)
        r = await c.patch(
            f"/api/v1/bookings/{booking_id}",
            json={"status": "draft"},
        )
        assert r.status_code == 400
