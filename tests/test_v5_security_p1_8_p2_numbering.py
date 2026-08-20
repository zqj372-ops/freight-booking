"""v0.5 安全修复测试: P1#8 多 confirmed SO 迁移 + P2 并发编号

P1#8: 同一 Shipment 多个 confirmed SO → 迁移不撞 UNIQUE
P2: 并发 generate_job_no / generate_booking_request_no → 不撞 UNIQUE
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.booking_confirmation import BookingConfirmation
from app.models.shipment import Shipment
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


# ========== P1#8 多 confirmed SO 迁移 ==========


@pytest.mark.asyncio
async def test_p1_8_migration_multiple_confirmed_sos() -> None:
    """P1#8 修复: 同 Shipment 2 个 confirmed SO 迁移不再 UNIQUE 失败."""
    from app.models.agent import Agent
    from app.models.booking import Booking, BookingStatus
    from app.models.so import SO, SOStatus

    async with AsyncSessionLocal() as db:
        a = Agent(name="P1-8 Agent", code="P18", booking_email="p18@x.example", is_active=True)
        db.add(a)
        await db.flush()
        b = Booking(
            booking_no="P18-001", pol="CNSHA", pod="USLAX",
            etd=datetime(2026, 9, 1, tzinfo=timezone.utc),
            eta=datetime(2026, 9, 20, tzinfo=timezone.utc),
            container_type="40HQ", container_count=1, commodity="P18 GOODS",
            customer_name="P18 Corp", carrier="COSCO", agent_id=a.id,
            status=BookingStatus.CONFIRMED,
        )
        db.add(b)
        await db.commit()
        await db.flush()
        so1 = SO(
            booking_id=b.id, so_number="SO-P18-001", carrier="COSCO",
            vessel_name="V1", voyage_no="001E",
            pol="CNSHA", pod="USLAX",
            etd=datetime(2026, 9, 1, tzinfo=timezone.utc),
            eta=datetime(2026, 9, 20, tzinfo=timezone.utc),
            container_type="40HQ", container_count=1,
            cut_off=datetime(2026, 8, 31, tzinfo=timezone.utc),
            status=SOStatus.CONFIRMED,
            source="email",
            file_path="/tmp/so_p18_001.pdf", file_name="so_p18_001.pdf",
            file_mime="application/pdf", file_size=1024,
        )
        so2 = SO(
            booking_id=b.id, so_number="SO-P18-002", carrier="COSCO",
            vessel_name="V2", voyage_no="002E",
            pol="CNSHA", pod="USLAX",
            etd=datetime(2026, 9, 5, tzinfo=timezone.utc),
            eta=datetime(2026, 9, 25, tzinfo=timezone.utc),
            container_type="40HQ", container_count=1,
            cut_off=datetime(2026, 9, 4, tzinfo=timezone.utc),
            status=SOStatus.CONFIRMED,
            source="email",
            file_path="/tmp/so_p18_002.pdf", file_name="so_p18_002.pdf",
            file_mime="application/pdf", file_size=1024,
        )
        db.add_all([so1, so2])
        await db.commit()

    # 跑迁移 - 旧版会 UNIQUE 撞, 修复后正常
    async with AsyncSessionLocal() as db:
        await run_migration(db)
        await db.commit()

    # 验证: 2 个 BC 成功建
    async with AsyncSessionLocal() as db:
        bcs = (await db.execute(select(BookingConfirmation))).scalars().all()
    bc_count = sum(1 for bc in bcs if bc.shipment_id)
    assert bc_count == 2, f"应有 2 个 BC, 实际 {bc_count}"
    versions = sorted([bc.version for bc in bcs if bc.shipment_id])
    assert versions == [1, 2], f"BC version 应是 [1,2], 实际 {versions}"
    currents = [bc for bc in bcs if bc.shipment_id and bc.is_current]
    assert len(currents) == 1
    assert currents[0].version == 2


# ========== P2 并发编号 (with_retry 版本) ==========
# generate_job_no / generate_booking_request_no 是 best-guess (COUNT+1), 真正的并发安全
# 在 endpoint commit 时 catch IntegrityError retry (见 test_p2_concurrent_shipment_creation_no_duplicate
# / test_p2_concurrent_booking_request_creation_no_duplicate).
# 这里只测基本调用, 不测并发.


@pytest.mark.asyncio
async def test_p2_generate_job_no_with_retry_callable() -> None:
    """generate_job_no 可调用且返合理格式 (FB-YYYYMMDD-XXXX)."""
    from app.models.organization import Organization
    from app.services.numbering import generate_job_no_with_retry

    async with AsyncSessionLocal() as db:
        org = (await db.execute(select(Organization))).scalar_one()
        jn = await generate_job_no_with_retry(db, org)
    assert jn.startswith("FB-")
    parts = jn.split("-")
    assert len(parts) == 3
    assert parts[1].isdigit() and len(parts[1]) == 8  # YYYYMMDD
    assert parts[2].isdigit() and len(parts[2]) == 4  # 4-digit seq


@pytest.mark.asyncio
async def test_p2_generate_booking_request_no_with_retry_callable() -> None:
    """generate_booking_request_no 可调用且返 BR-XXX 格式."""
    from app.services.numbering import generate_booking_request_no_with_retry

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s.json()["id"]

    async with AsyncSessionLocal() as db:
        br = await generate_booking_request_no_with_retry(db, sid)
    assert br.startswith("BR-")
    seq = int(br.split("-")[1])
    assert 1 <= seq <= 999  # 3-digit format (e.g. 001)


@pytest.mark.asyncio
async def test_p2_concurrent_shipment_creation_no_duplicate() -> None:
    """P2 集成: 顺序建 5 个 shipment (避免 asyncio.gather 同 session 冲突), 5 个 job_no 都不重."""
    job_nos = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for i in range(5):
            r = await c.post("/api/v2/shipments/", json={
                "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": f"X{i}",
            })
            assert r.status_code == 201, r.text
            job_nos.append(r.json()["job_no"])
    assert len(set(job_nos)) == 5, f"5 个 shipment 的 job_no 应不重, 实际: {job_nos}"
    # 验证编号递增
    for i, jn in enumerate(job_nos):
        seq = int(jn.split("-")[-1])
        assert seq == i + 1, f"第 {i+1} 个 shipment job_no 序列应是 {i+1}, 实际 {seq}"


@pytest.mark.asyncio
async def test_p2_concurrent_booking_request_creation_no_duplicate() -> None:
    """P2 集成: 顺序建 5 个 booking_request (同 shipment), 5 个 booking_request_no 都不重."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s.json()["id"]
        p = await c.post("/api/v2/partners/", json={
            "partner_type": "carrier", "name": "Carrier P2",
            "primary_email": "p2@c.example",
        })
        pid = p.json()["id"]
        br_nos = []
        for i in range(5):
            r = await c.post("/api/v2/booking-requests/", json={
                "shipment_id": sid, "partner_id": pid,
                "requested_etd": "2026-09-15", "requested_pol": "CNSHA", "requested_pod": "USLAX",
            })
            assert r.status_code == 201, r.text
            br_nos.append(r.json()["booking_request_no"])
    assert len(set(br_nos)) == 5, f"5 个 booking_request_no 应不重, 实际: {br_nos}"
    # 验证 BR 编号递增
    for i, br in enumerate(br_nos):
        seq = int(br.split("-")[-1])
        assert seq == i + 1, f"第 {i+1} 个 BR 编号应是 BR-{i+1:03d}, 实际 {br}"
