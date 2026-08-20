"""v0.5 安全修复测试: P1#4 双 is_current + P1#5 overrides 白名单 + P1#6 原子事务

覆盖:
- P1#4: v1 accepted + v2 received (未审核) 时不双 current
  - next_action 500 (scalar_one_or_none 两行)
  - 主列表泄露未审核 v2 数据
- P1#5: overrides 拒 organization_id / shipment_id / version / id 字段
- P1#6: workflow 抛异常时全 rollback (BC 状态 / Shipment / 旧 BC 切换都回滚)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.booking_confirmation import (
    BookingConfirmation,
    BookingConfirmationStatus,
)
from app.models.shipment import Shipment


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


async def _make_shipment(c) -> str:
    s = await c.post("/api/v2/shipments/", json={
        "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
    })
    return s.json()["id"]


async def _make_bc(c, sid: str, so_no: str, version: int = 1, is_current: bool = True) -> dict:
    """直接建一个 BC (bypass acceptance)"""
    from app.models.booking_confirmation import BookingConfirmationReviewStatus
    async with AsyncSessionLocal() as db:
        org_id = (await db.execute(select(Shipment).where(Shipment.id == sid))).scalar_one().organization_id
        bc = BookingConfirmation(
            id=f"bc_{so_no}",
            organization_id=org_id,
            shipment_id=sid,
            so_no=so_no,
            vessel_name="V1",
            voyage_no="001E",
            pol="CNSHA",
            pod="USLAX",
            etd=date(2026, 9, 15),
            eta=date(2026, 9, 25),
            container_type="40HQ",
            container_count=1,
            version=version,
            is_current=is_current,
            status=BookingConfirmationStatus.MATCHED_PENDING,
            review_status=BookingConfirmationReviewStatus.NEEDS_REVIEW,
        )
        db.add(bc)
        await db.commit()
        await db.refresh(bc)
        return {"id": bc.id, "version": bc.version, "is_current": bc.is_current}


# ========== P1#4: 双 is_current 护栏 ==========


@pytest.mark.asyncio
async def test_p1_4_v2_received_when_v1_accepted_no_double_current() -> None:
    """v1 accepted (is_current=true) + v2 新建 (未审核) 时, v2 不设 is_current=true."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        # 直接建 v1, 标 ACCEPTED + is_current=True
        async with AsyncSessionLocal() as db:
            s = (await db.execute(select(Shipment).where(Shipment.id == sid))).scalar_one()
            from app.models.booking_confirmation import (
                BookingConfirmation as BCM,
                BookingConfirmationReviewStatus as BCR,
            )
            bc1 = BCM(
                id="bc_v1",
                organization_id=s.organization_id,
                shipment_id=sid,
                so_no="SO-V1",
                vessel_name="V1", voyage_no="001E",
                pol="CNSHA", pod="USLAX",
                etd=date(2026, 9, 15), eta=date(2026, 9, 25),
                container_type="40HQ", container_count=1,
                version=1, is_current=True,
                status=BookingConfirmationStatus.ACCEPTED,
                review_status=BCR.REVIEWED,
                accepted_at=datetime.now(timezone.utc),
            )
            db.add(bc1)
            await db.commit()

        # 新建 v2 (通过 endpoint)
        r = await c.post("/api/v2/booking-confirmations/", json={
            "shipment_id": sid,
            "so_no": "SO-V2",
            "vessel_name": "V2", "voyage_no": "002E",
            "pol": "CNSHA", "pod": "USLAX",
            "etd": "2026-09-16", "eta": "2026-09-26",
            "container_type": "40HQ", "container_count": 1,
        })
        assert r.status_code == 201, r.text
        v2 = r.json()
        # P1#4 修复: v2 不应该是 is_current (因为已有 accepted v1 current)
        assert v2["is_current"] is False, "v2 不应被设 is_current=true, 避免双 current"

        # 验证: 任何 is_current=true 都只有 v1 一行
        r2 = await c.get(f"/api/v2/booking-confirmations/?shipment_id={sid}&is_current=true")
        currents = r2.json()
        assert len(currents) == 1
        assert currents[0]["id"] == "bc_v1"


@pytest.mark.asyncio
async def test_p1_4_doc_checklist_no_500_when_pending_v2() -> None:
    """主列表/文件齐套 不会因双 current 而 500 (旧版 scalar_one_or_none 报 2 行)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        # 直接手动造"双 current" 数据 (模拟修复前的 v2 received 未审核 bug)
        async with AsyncSessionLocal() as db:
            s = (await db.execute(select(Shipment).where(Shipment.id == sid))).scalar_one()
            from app.models.booking_confirmation import (
                BookingConfirmation as BCM,
                BookingConfirmationReviewStatus as BCR,
            )
            # v1 accepted
            db.add(BCM(
                id="bc_v1_legacy", organization_id=s.organization_id, shipment_id=sid,
                so_no="SO-V1", vessel_name="V1", voyage_no="001E",
                pol="CNSHA", pod="USLAX",
                etd=date(2026, 9, 15), eta=date(2026, 9, 25),
                container_type="40HQ", container_count=1,
                version=1, is_current=True,
                status=BookingConfirmationStatus.ACCEPTED,
                review_status=BCR.REVIEWED,
                accepted_at=datetime.now(timezone.utc),
            ))
            # v2 received pending (也有 is_current=true 旧 bug 状态)
            db.add(BCM(
                id="bc_v2_legacy", organization_id=s.organization_id, shipment_id=sid,
                so_no="SO-V2-LEGACY", vessel_name="V2", voyage_no="002E",
                pol="CNSHA", pod="USLAX",
                etd=date(2026, 9, 16), eta=date(2026, 9, 26),
                container_type="40HQ", container_count=1,
                version=2, is_current=True,  # 旧 bug: 仍 current
                status=BookingConfirmationStatus.MATCHED_PENDING,
                review_status=BCR.NEEDS_REVIEW,
            ))
            await db.commit()

        # 即使存在双 current, doc-checklist 必须不 500
        r = await c.get(f"/api/v2/shipments/{sid}/document-checklist")
        assert r.status_code == 200, f"doc-checklist 500: {r.text}"


# ========== P1#5: overrides 白名单 ==========


@pytest.mark.asyncio
async def test_p1_5_overrides_rejects_organization_id() -> None:
    """P1#5: overrides 不能改 organization_id."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        bc = await _make_bc(c, sid, "SO-501", version=1)
        r = await c.post(f"/api/v2/booking-confirmations/{bc['id']}/accept", json={
            "overrides": {"organization_id": "attacker-org"},
            "reason": "test override attempt",
        })
        assert r.status_code == 400
        assert "organization_id" in r.json()["detail"]
        assert "not allowed" in r.json()["detail"]


@pytest.mark.asyncio
async def test_p1_5_overrides_rejects_shipment_id() -> None:
    """P1#5: overrides 不能改 shipment_id."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        bc = await _make_bc(c, sid, "SO-502", version=1)
        r = await c.post(f"/api/v2/booking-confirmations/{bc['id']}/accept", json={
            "overrides": {"shipment_id": "other-ship"},
            "reason": "test reject",
        })
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_p1_5_overrides_rejects_version_and_id() -> None:
    """P1#5: overrides 不能改 version / id."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        bc = await _make_bc(c, sid, "SO-503", version=1)
        for evil_field in ["version", "id", "status", "is_current", "supersedes_id"]:
            r = await c.post(f"/api/v2/booking-confirmations/{bc['id']}/accept", json={
                "overrides": {evil_field: 999 if evil_field == "version" else "x"},
                "reason": "test evil field",
            })
            assert r.status_code == 400, f"{evil_field} should be rejected, got {r.status_code}"


@pytest.mark.asyncio
async def test_p1_5_overrides_allows_business_fields() -> None:
    """P1#5: 业务字段 (etd, vessel_name 等) 允许 overrides."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        bc = await _make_bc(c, sid, "SO-504", version=1)
        r = await c.post(f"/api/v2/booking-confirmations/{bc['id']}/accept", json={
            "overrides": {
                "vessel_name": "NEW VESSEL",
                "voyage_no": "999W",
                "etd": "2026-10-01",
            },
            "reason": "船期改 v2 测试",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["vessel_name"] == "NEW VESSEL"
        assert d["voyage_no"] == "999W"


# ========== P1#6: 原子事务 ==========


@pytest.mark.asyncio
async def test_p1_6_workflow_failure_rolls_back_bc_changes() -> None:
    """P1#6: workflow 抛异常时, BC / Shipment / 旧 BC 切换都回滚 (原 bug 半完成)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)

        # 建 v1, accept 成 current
        async with AsyncSessionLocal() as db:
            from app.models.booking_confirmation import (
                BookingConfirmation as BCM,
                BookingConfirmationReviewStatus as BCR,
            )
            s = (await db.execute(select(Shipment).where(Shipment.id == sid))).scalar_one()
            bc1 = BCM(
                id="bc_v1_atomic", organization_id=s.organization_id, shipment_id=sid,
                so_no="SO-ATOMIC-V1", vessel_name="V1", voyage_no="001E",
                pol="CNSHA", pod="USLAX",
                etd=date(2026, 9, 15), eta=date(2026, 9, 25),
                container_type="40HQ", container_count=1,
                version=1, is_current=True,
                status=BookingConfirmationStatus.ACCEPTED,
                review_status=BCR.REVIEWED,
                accepted_at=datetime.now(timezone.utc),
            )
            db.add(bc1)
            await db.commit()

        # 建 v2 pending
        bc2 = await _make_bc(c, sid, "SO-ATOMIC-V2", version=2, is_current=False)

        # Mock workflow.on_booking_confirmation_accepted 让它抛异常
        from app.api.v2 import booking_confirmation as bc_module

        async def boom(*args, **kwargs):
            raise RuntimeError("injected workflow failure")

        # 注意: endpoint import 是 `from app.services.workflow import on_booking_confirmation_accepted`
        # 注入应在 services.workflow (原始模块)
        with patch("app.services.workflow.on_booking_confirmation_accepted", side_effect=boom):
            r = await c.post(f"/api/v2/booking-confirmations/{bc2['id']}/accept", json={
                "reason": "test atomic rollback",
            })
            assert r.status_code == 500
            assert "rolled back" in r.json()["detail"].lower()

        # 验证: v2 状态没被改成 ACCEPTED
        async with AsyncSessionLocal() as db:
            v2_db = (await db.execute(
                select(BookingConfirmation).where(BookingConfirmation.id == bc2['id'])
            )).scalar_one()
            assert v2_db.status != BookingConfirmationStatus.ACCEPTED, "v2 BC 不应被 ACCEPTED"

            v1_db = (await db.execute(
                select(BookingConfirmation).where(BookingConfirmation.id == "bc_v1_atomic")
            )).scalar_one()
            # v1 仍是 current (没被切换)
            assert v1_db.is_current is True
            assert v1_db.status == BookingConfirmationStatus.ACCEPTED

            # Shipment stage 没推进到 booked
            s_db = (await db.execute(
                select(Shipment).where(Shipment.id == sid)
            )).scalar_one()
            assert s_db.stage.value != "booked", f"Shipment 不应被推进, 实际 {s_db.stage.value}"
