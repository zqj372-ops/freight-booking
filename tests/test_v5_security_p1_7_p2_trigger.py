"""v0.5 安全修复测试: P1#7 cancelled 终态 + P2 trigger 幂等

P1#7: cancelled Shipment 不允许加 milestone / task / exception
P2: trigger fire_event 重复同 event 应该幂等 (旧 bug: fire 2 次建 4 task)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
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


async def _make_shipment(c, stage: str = "draft") -> str:
    """建业务单, 可选立即 cancel."""
    s = await c.post("/api/v2/shipments/", json={
        "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
    })
    sid = s.json()["id"]
    if stage == "cancelled":
        r = await c.post(f"/api/v2/shipments/{sid}/stage", json={
            "stage": "cancelled",
            "reason": "客户取消业务测试",
        })
        assert r.status_code == 200
    return sid


# ========== P1#7 cancelled 终态护栏 ==========


@pytest.mark.asyncio
async def test_p1_7_cancelled_shipment_blocks_milestone() -> None:
    """cancelled Shipment 不允许加 milestone."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c, stage="cancelled")
        r = await c.post(f"/api/v2/workflow/shipments/{sid}/milestones", json={
            "code": "departed",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "manual",
        })
        assert r.status_code == 400
        assert "cancelled" in r.json()["detail"].lower()
        assert "terminal" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_p1_7_cancelled_shipment_blocks_task() -> None:
    """cancelled Shipment 不允许加 task."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c, stage="cancelled")
        r = await c.post(f"/api/v2/workflow/shipments/{sid}/tasks", json={
            "code": "confirm_booking",
            "title": "cancelled 后的 task",
        })
        assert r.status_code == 400
        assert "cancelled" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_p1_7_cancelled_shipment_blocks_exception() -> None:
    """cancelled Shipment 不允许加 exception."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c, stage="cancelled")
        r = await c.post(f"/api/v2/workflow/shipments/{sid}/exceptions", json={
            "code": "schedule_changed",
            "severity": "warning",
        })
        assert r.status_code == 400
        assert "cancelled" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_p1_7_non_cancelled_shipment_still_works() -> None:
    """非 cancelled Shipment 加 milestone/task/exception 正常 (sanity check)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c, stage="draft")

        # milestone OK
        r = await c.post(f"/api/v2/workflow/shipments/{sid}/milestones", json={
            "code": "booking_request_sent",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "manual",
        })
        assert r.status_code == 201

        # task OK
        r = await c.post(f"/api/v2/workflow/shipments/{sid}/tasks", json={
            "code": "confirm_booking", "title": "test task",
        })
        assert r.status_code == 201

        # exception OK
        r = await c.post(f"/api/v2/workflow/shipments/{sid}/exceptions", json={
            "code": "schedule_changed", "severity": "warning",
        })
        assert r.status_code == 201


# ========== P2: trigger fire_event 幂等 ==========


@pytest.mark.asyncio
async def test_p2_trigger_fire_event_idempotent() -> None:
    """fire_event 重复 fire 同 event 应幂等 (第二次返 [], 不建新 task)."""
    from app.services.triggers import TriggerEvent, fire_event

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c, stage="draft")
        # 拿到 shipment 对象
        async with AsyncSessionLocal() as db:
            shipment = (await db.execute(
                select(Shipment).where(Shipment.id == sid)
            )).scalar_one()

        # 第一次 fire
        async with AsyncSessionLocal() as db:
            shipment = (await db.execute(
                select(Shipment).where(Shipment.id == sid)
            )).scalar_one()
            tasks_1 = await fire_event(db, event=TriggerEvent.SO_RECEIVED, shipment=shipment)
            await db.commit()
        assert len(tasks_1) > 0, "首次 fire 应建 task"
        first_count = len(tasks_1)

        # 第二次 fire 同 event 应幂等
        async with AsyncSessionLocal() as db:
            shipment = (await db.execute(
                select(Shipment).where(Shipment.id == sid)
            )).scalar_one()
            tasks_2 = await fire_event(db, event=TriggerEvent.SO_RECEIVED, shipment=shipment)
            await db.commit()
        # 第二次应返 [] (跳过)
        assert tasks_2 == [], f"重复 fire 应跳过, 实际建了 {len(tasks_2)} task"

        # 验证 DB 中任务总数没翻倍
        from app.models.task import Task
        async with AsyncSessionLocal() as db:
            all_tasks = (await db.execute(
                select(Task).where(Task.shipment_id == sid)
            )).scalars().all()
        trigger_tasks = [t for t in all_tasks if (t.context or {}).get("trigger_event") == "so_received"]
        assert len(trigger_tasks) == first_count, f"trigger task 应只有 {first_count} 个, 实际 {len(trigger_tasks)}"


@pytest.mark.asyncio
async def test_p2_trigger_after_completion_can_fire_again() -> None:
    """task 完成 (status=DONE) 后, 同 event 再次 fire 可建新 task (允许)."""
    from app.services.triggers import TriggerEvent, fire_event
    from app.models.task import Task, TaskStatus

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c, stage="draft")

        # 第一次 fire
        async with AsyncSessionLocal() as db:
            shipment = (await db.execute(
                select(Shipment).where(Shipment.id == sid)
            )).scalar_one()
            tasks_1 = await fire_event(db, event=TriggerEvent.SEALED, shipment=shipment)
            await db.commit()
        assert len(tasks_1) > 0

        # 把所有 sealed task 标 done
        async with AsyncSessionLocal() as db:
            sealed_tasks = (await db.execute(
                select(Task).where(Task.shipment_id == sid)
            )).scalars().all()
            for t in sealed_tasks:
                if (t.context or {}).get("trigger_event") == "sealed":
                    t.status = TaskStatus.DONE
                    t.completed_at = datetime.now(timezone.utc)
            await db.commit()

        # 第二次 fire (上次已 done, 应该允许再建)
        async with AsyncSessionLocal() as db:
            shipment = (await db.execute(
                select(Shipment).where(Shipment.id == sid)
            )).scalar_one()
            tasks_2 = await fire_event(db, event=TriggerEvent.SEALED, shipment=shipment)
            await db.commit()
        assert len(tasks_2) > 0, "上次 task 已 done, 再次 fire 应建新 task"
