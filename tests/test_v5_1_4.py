"""v0.5 阶段 1.4 测试 - Milestone + Task + OperationalException + 9 步端到端 demo

按 docs/domain/core-workflow.md §6 跑一遍完整主链路.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models import (
    OperationalException,
    Shipment,
    ShipmentStage,
    Task,
    TaskStatus,
)
from app.models.operational_exception import ExceptionStatus as _ExceptionStatus  # noqa


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


async def _post(client, path, json=None, **kw):
    r = await client.post(path, json=json or {}, **kw)
    assert r.status_code in (200, 201), f"{path}: {r.status_code} {r.text}"
    return r.json()


@pytest.mark.asyncio
async def test_workflow_9_step_end_to_end() -> None:
    """完整 9 步主链路: 建单 → 发订舱 → 收SO → 匹配 → 接受 → 自动开 task → 提柜 → 装船 → 开船"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # ===== 步骤 1: 建业务单 =====
        customer = await _post(c, "/api/v2/partners/", {
            "partner_type": "customer", "name": "ACME",
        })
        agent = await _post(c, "/api/v2/partners/", {
            "partner_type": "agent_l1", "name": "代理A", "short_code": "AGT-A",
        })
        s = await _post(c, "/api/v2/shipments/", {
            "customer_partner_id": customer["id"],
            "current_partner_id": agent["id"],
            "pol": "CNSHA", "pod": "USLAX",
            "target_etd": "2026-09-15",
            "commodity": "ELECTRONIC PARTS",
        })
        assert s["stage"] == "draft"
        assert s["job_no"].startswith("FB-")
        shipment_id = s["id"]

        # ===== 步骤 2: 发订舱申请 =====
        br = await _post(c, "/api/v2/booking-requests/", {
            "shipment_id": shipment_id,
            "partner_id": agent["id"],
            "requested_etd": "2026-09-15",
            "requested_pol": "CNSHA",
            "requested_pod": "USLAX",
            "requested_container_type": "40HQ",
        })
        assert br["booking_request_no"] == "BR-001"
        assert br["status"] == "draft"

        # dry_run send (避免真实 SMTP)
        r = await c.post(f"/api/v2/booking-requests/{br['id']}/send", json={
            "template_code": "booking_request",
            "to_emails": ["booking@agt-a.com"],
            "dry_run": True,
        })
        assert r.status_code == 200
        # dry_run 不改 status
        br2 = (await c.get(f"/api/v2/booking-requests/{br['id']}")).json()
        assert br2["status"] == "draft"

        # ===== 步骤 3: 模拟"收到 SO" (上传 PDF + 系统抽取) =====
        # 我们直接调 API 创建 BC, 跳过文件上传
        si_cutoff = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        bc = await _post(c, "/api/v2/booking-confirmations/", {
            "shipment_id": shipment_id,
            "booking_request_id": br["id"],
            "carrier": "MAERSK",
            "carrier_booking_no": "MAE1234567",
            "vessel_name": "MAERSK HONG KONG",
            "voyage_no": "V.345E",
            "pol": "CNSHA", "pod": "USLAX",
            "etd": "2026-09-15", "eta": "2026-10-05",
            "si_cutoff_at": si_cutoff,
            "cy_cutoff_at": (datetime.now(timezone.utc) + timedelta(days=4)).isoformat(),
            "container_type": "40HQ", "container_count": 1,
        })
        assert bc["status"] == "matched_pending"
        assert bc["is_current"] is True

        # ===== 步骤 4: 接受 BC → 自动派生 stage + 创建 milestone + 开 task + 关 task =====
        r = await c.post(f"/api/v2/booking-confirmations/{bc['id']}/accept", json={
            "reason": "船期和柜型与申请一致, 接受 SO",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"

        # Shipment 字段被写入 + stage 推到 booked
        s_after = (await c.get(f"/api/v2/shipments/{shipment_id}")).json()
        assert s_after["stage"] == "booked"
        assert s_after["carrier_booking_no"] == "MAE1234567"
        assert s_after["current_carrier"] == "MAERSK"

        # ===== 步骤 5: 验证 milestone / task / exception =====
        # Milestone 自动创建
        ms = (await c.get(f"/api/v2/workflow/shipments/{shipment_id}/milestones")).json()
        assert len(ms) == 1
        assert ms[0]["code"] == "booking_confirmation_accepted"
        assert ms[0]["source"] == "auto"

        # Task 自动开 (安排提柜 / 录入柜号 / 提交 SI / 提交 VGM)
        tasks = (await c.get(f"/api/v2/workflow/shipments/{shipment_id}/tasks")).json()
        codes = [t["code"] for t in tasks]
        assert "arrange_pickup" in codes
        assert "record_container_no" in codes
        assert "submit_si" in codes
        assert "submit_vgm" in codes
        assert all(t["status"] == "pending" for t in tasks)

        # ===== 步骤 6: 录入提柜 → 自动关 task + 自动创建 milestone =====
        # 模拟提柜时间
        pickup_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        # 录入柜号 (先在 Container 上)
        containers = (await c.get(f"/api/v2/shipments/{shipment_id}/containers")).json()
        cid = containers[0]["id"]
        r = await c.patch(f"/api/v2/containers/{cid}", json={
            "container_no": "MSKU1234567",
            "seal_no": "SEAL-001",
            "pickup_location": "上海外高桥",
            "pickup_time": pickup_time,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "picked_up"

        # 录入提柜 milestone (系统/手动)
        r = await c.post(f"/api/v2/workflow/shipments/{shipment_id}/milestones", json={
            "code": "container_picked_up",
            "occurred_at": pickup_time,
            "container_no": "MSKU1234567",
            "location": "上海外高桥",
        })
        assert r.status_code == 201

        # record_container_no / arrange_pickup task 应被自动关闭
        tasks = (await c.get(f"/api/v2/workflow/shipments/{shipment_id}/tasks?status=pending")).json()
        pending_codes = [t["code"] for t in tasks]
        assert "record_container_no" not in pending_codes
        assert "arrange_pickup" not in pending_codes
        # submit_si / submit_vgm 还 pending (没录对应 milestone)
        assert "submit_si" in pending_codes
        assert "submit_vgm" in pending_codes

        # ===== 步骤 7: 装船 → container.status=loaded + 新 milestone =====
        loaded_time = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        r = await c.patch(f"/api/v2/containers/{cid}", json={"loaded_time": loaded_time})
        assert r.status_code == 200
        assert r.json()["status"] == "loaded"

        r = await c.post(f"/api/v2/workflow/shipments/{shipment_id}/milestones", json={
            "code": "container_loaded",
            "occurred_at": loaded_time,
        })
        assert r.status_code == 201

        # ===== 步骤 8: 提交 SI → task 自动关 =====
        r = await c.post(f"/api/v2/workflow/shipments/{shipment_id}/milestones", json={
            "code": "si_submitted",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })
        assert r.status_code == 201

        tasks = (await c.get(f"/api/v2/workflow/shipments/{shipment_id}/tasks?status=pending")).json()
        pending_codes = [t["code"] for t in tasks]
        assert "submit_si" not in pending_codes
        assert "submit_vgm" in pending_codes  # vgm 还没录

        # ===== 步骤 9: 开船 → derived stage = departed =====
        r = await c.post(f"/api/v2/workflow/shipments/{shipment_id}/milestones", json={
            "code": "departed",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "location": "上海港",
        })
        assert r.status_code == 201

        # derived_stage API
        r = await c.get(f"/api/v2/workflow/shipments/{shipment_id}/derived-stage")
        assert r.status_code == 200
        assert r.json()["derived_stage"] == "departed"


@pytest.mark.asyncio
async def test_exception_schedule_changed_then_auto_close() -> None:
    """客户改 ETD, 收 BC v2 → schedule_changed exception 自动 close"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        customer = await _post(c, "/api/v2/partners/", {"partner_type": "customer", "name": "C"})
        agent = await _post(c, "/api/v2/partners/", {"partner_type": "agent_l1", "name": "A"})
        s = await _post(c, "/api/v2/shipments/", {
            "customer_partner_id": customer["id"], "pol": "CNSHA", "pod": "USLAX",
            "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s["id"]

        # BC v1
        bc1 = await _post(c, "/api/v2/booking-confirmations/", {
            "shipment_id": sid, "carrier": "MAERSK",
            "etd": "2026-09-15", "eta": "2026-10-05",
        })
        await c.post(f"/api/v2/booking-confirmations/{bc1['id']}/accept", json={"reason": "船期 OK 接受 v1"})

        # BC v2 (改时间, 触发 schedule_changed exception)
        bc2 = await _post(c, "/api/v2/booking-confirmations/", {
            "shipment_id": sid, "carrier": "MAERSK",
            "etd": "2026-09-18", "eta": "2026-10-08",
        })
        await c.post(f"/api/v2/booking-confirmations/{bc2['id']}/accept", json={"reason": "船期改期, 接受 v2"})

        # 应该有 1 个 open schedule_changed
        exs = (await c.get(f"/api/v2/workflow/shipments/{sid}/exceptions?status=open")).json()
        sc = [e for e in exs if e["code"] == "schedule_changed"]
        assert len(sc) == 1
        assert sc[0]["context"]["old_etd"] == "2026-09-15"
        assert sc[0]["context"]["new_etd"] == "2026-09-18"

        # BC v3 (再次改时间) — 应该 auto_close 上一个 schedule_changed
        bc3 = await _post(c, "/api/v2/booking-confirmations/", {
            "shipment_id": sid, "carrier": "MAERSK",
            "etd": "2026-09-20", "eta": "2026-10-10",
        })
        await c.post(f"/api/v2/booking-confirmations/{bc3['id']}/accept", json={"reason": "再改时间 v3"})

        # 之前那个 schedule_changed 应该 auto_closed
        all_exs = (await c.get(f"/api/v2/workflow/shipments/{sid}/exceptions")).json()
        sc_statuses = [e["status"] for e in all_exs if e["code"] == "schedule_changed"]
        assert "auto_closed" in sc_statuses


@pytest.mark.asyncio
async def test_manual_exception_resolve() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s["id"]

        ex = await _post(c, f"/api/v2/workflow/shipments/{sid}/exceptions", {
            "code": "missing_container_no", "severity": "warning",
        })
        assert ex["status"] == "open"

        # 解决
        r = await c.post(f"/api/v2/workflow/exceptions/{ex['id']}/resolve", json={
            "resolution": "已电话联系船公司, 确认柜号待补录",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "resolved"
        assert r.json()["resolution"] == "已电话联系船公司, 确认柜号待补录"
        assert r.json()["resolved_by_name"] == "anonymous"


@pytest.mark.asyncio
async def test_audit_logs_for_workflow_operations() -> None:
    """workflow 操作 (create task / record milestone / accept SO) 都留 audit log"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        customer = await _post(c, "/api/v2/partners/", {"partner_type": "customer", "name": "C"})
        s = await _post(c, "/api/v2/shipments/", {
            "customer_partner_id": customer["id"], "pol": "CNSHA", "pod": "USLAX",
            "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s["id"]

        # 建 task
        t = await _post(c, f"/api/v2/workflow/shipments/{sid}/tasks", {
            "code": "submit_si", "title": "提交 SI 补料",
        })

        # 建 milestone
        m = await _post(c, f"/api/v2/workflow/shipments/{sid}/milestones", json={
            "code": "container_picked_up",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })

        # audit log
        t_logs = (await c.get(f"/api/v2/audit-logs/by-entity/task/{t['id']}")).json()
        assert any(l["action"] == "create" for l in t_logs)
        m_logs = (await c.get(f"/api/v2/audit-logs/by-entity/milestone/{m['id']}")).json()
        assert any(l["action"] == "record" for l in m_logs)


@pytest.mark.asyncio
async def test_task_complete_then_done() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s["id"]
        t = await _post(c, f"/api/v2/workflow/shipments/{sid}/tasks", {
            "code": "submit_si", "title": "提交 SI",
        })
        # 标完成
        r = await c.patch(f"/api/v2/workflow/tasks/{t['id']}", json={
            "status": "done",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "done"
        assert r.json()["completed_at"] is not None
        assert r.json()["completed_by_name"] == "anonymous"
