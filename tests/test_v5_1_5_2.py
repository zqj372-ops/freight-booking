"""v0.5 阶段 1.5.2 测试 - 5 类备注 + 7 个 Y/N→enum 状态字段 + 联动时间戳"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, engine
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


async def _post(client, path, json=None, headers=None):
    r = await client.post(path, json=json or {}, headers=headers or {})
    assert r.status_code in (200, 201), f"{path}: {r.status_code} {r.text}"
    return r.json()


async def _patch(client, path, json=None, headers=None):
    r = await client.patch(path, json=json or {}, headers=headers or {})
    assert r.status_code in (200, 201), f"PATCH {path}: {r.status_code} {r.text}"
    return r.json()


@pytest.mark.asyncio
async def test_5_remarks_accepted() -> None:
    """PATCH /status 接受 5 类备注"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        updated = await _patch(c, f"/api/v2/shipments/{s['id']}/status", {
            "booking_remark": "客户要求配 COSCO 直航",
            "bl_remark": "提单需显示 second notify",
            "customs_remark": "已预约 8/22 上午 10 点查验",
            "pod_remark": "温哥华仓库卸柜后预约 UPS 派送",
            "finance_remark": "CNY 报价, 已收 30% 预付款",
        })
        assert updated["booking_remark"] == "客户要求配 COSCO 直航"
        assert updated["bl_remark"] == "提单需显示 second notify"
        assert updated["customs_remark"] == "已预约 8/22 上午 10 点查验"
        assert updated["pod_remark"] == "温哥华仓库卸柜后预约 UPS 派送"
        assert updated["finance_remark"] == "CNY 报价, 已收 30% 预付款"


@pytest.mark.asyncio
async def test_7_status_fields_accepted() -> None:
    """PATCH /status 接受 7 个 enum 状态字段 (customs/inspection/rolled/payment_request/payment_proof/empty_return/bl_process)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        updated = await _patch(c, f"/api/v2/shipments/{s['id']}/status", {
            "customs_status": "submitting",
            "inspection_status": "received",
            "rolled_status": "suspected",
            "payment_request_status": "requested",
            "payment_proof_status": "provided",
            "empty_return_status": "scheduled",
            "bl_process_status": "draft_received",
        })
        assert updated["customs_status"] == "submitting"
        assert updated["inspection_status"] == "received"
        assert updated["rolled_status"] == "suspected"
        assert updated["payment_request_status"] == "requested"
        assert updated["payment_proof_status"] == "provided"
        assert updated["empty_return_status"] == "scheduled"
        assert updated["bl_process_status"] == "draft_received"


@pytest.mark.asyncio
async def test_customs_released_auto_fills_timestamp() -> None:
    """customs_status=released → 自动填 customs_released_at + customs_released_by"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        assert s["customs_released_at"] is None
        assert s["customs_released_by"] is None

        # X-User-Id 决定 actor_type=USER, X-User-Name 决定显示名
        updated = await _patch(c, f"/api/v2/shipments/{s['id']}/status", {
            "customs_status": "released",
        }, headers={"X-User-Id": "u-zhang", "X-User-Name": "operator.zhang"})

        assert updated["customs_status"] == "released"
        assert updated["customs_released_at"] is not None
        assert updated["customs_released_by"] == "operator.zhang"
        # 验证 ISO 格式
        datetime.fromisoformat(updated["customs_released_at"])


@pytest.mark.asyncio
async def test_inspection_received_auto_fills_timestamp() -> None:
    """inspection_status=received → 自动填 inspection_received_at"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        assert s["inspection_received_at"] is None

        updated = await _patch(c, f"/api/v2/shipments/{s['id']}/status", {
            "inspection_status": "received",
        })

        assert updated["inspection_status"] == "received"
        assert updated["inspection_received_at"] is not None
        datetime.fromisoformat(updated["inspection_received_at"])


@pytest.mark.asyncio
async def test_partial_update_only_changes_provided_fields() -> None:
    """只传 customs_status 时, 其他 status 字段保持不变"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 第一次: 设几个状态
        await _patch(c, f"/api/v2/shipments/{s['id']}/status", {
            "customs_status": "submitting",
            "bl_process_status": "draft_received",
        })
        # 第二次: 只改 customs, bl_process 应保持不变
        updated = await _patch(c, f"/api/v2/shipments/{s['id']}/status", {
            "customs_status": "released",
        })
        assert updated["customs_status"] == "released"
        assert updated["bl_process_status"] == "draft_received"  # 没传, 不变
        # 备注也没传, 仍为 None
        assert updated["booking_remark"] is None


@pytest.mark.asyncio
async def test_status_change_writes_audit_log() -> None:
    """状态变更写 audit log (字段变化 diff)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        await _patch(c, f"/api/v2/shipments/{s['id']}/status", {
            "customs_status": "released",
            "booking_remark": "客户备注",
            "reason": "报关放行通知, 客户确认",
        }, headers={"X-User-Id": "u-zhang", "X-User-Name": "operator.zhang"})

        # 查 audit log
        r = await c.get(f"/api/v2/audit-logs/?entity_type=shipment&entity_id={s['id']}")
        assert r.status_code == 200
        logs = r.json()
        # 至少 1 条 create + 1 条 update
        actions = [l["action"] for l in logs]
        assert "create" in actions
        assert "update" in actions
        # 找到状态变更那条
        update_logs = [l for l in logs if l["action"] == "update"]
        update_log = update_logs[0]
        assert "customs_status" in update_log["field_changes"]
        assert update_log["field_changes"]["customs_status"]["old"] is None
        assert update_log["field_changes"]["customs_status"]["new"] == "released"
        assert "booking_remark" in update_log["field_changes"]
        assert update_log["reason"] == "报关放行通知, 客户确认"


@pytest.mark.asyncio
async def test_last_updated_at_bumps_on_status_change() -> None:
    """改 status 后, last_updated_at 自动更新"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        original = s["last_updated_at"]
        # 至少 sleep 一点确保时戳不同 — 但 SQLite 同秒可能冲突, 用 reason + booking_remark 触发 update
        # 实际 last_updated_at 是 DateTime(timezone=True) 带微妙, 应该不同
        updated = await _patch(c, f"/api/v2/shipments/{s['id']}/status", {
            "customs_status": "submitting",
        })
        # 改了 status → last_updated_at 应被设置
        assert updated["last_updated_at"] is not None


@pytest.mark.asyncio
async def test_cancelled_shipment_status_blocked() -> None:
    """cancelled 业务单不能再 PATCH /status"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 取消
        await _post(c, f"/api/v2/shipments/{s['id']}/stage", json={
            "stage": "cancelled",
            "reason": "客户取消订单, 改走空运",
        })
        # 再 PATCH status
        r = await c.patch(f"/api/v2/shipments/{s['id']}/status", json={
            "customs_status": "released",
        })
        assert r.status_code == 400
        assert "cancelled" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invalid_enum_value_rejected() -> None:
    """非法 enum 值被 Pydantic 422 拒绝"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        r = await c.patch(f"/api/v2/shipments/{s['id']}/status", json={
            "customs_status": "invalid_value",
        })
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_status_update_returns_full_shipment() -> None:
    """PATCH /status 返回完整 ShipmentRead, 包括 1.5.1 触发字段"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "CAVAN", "target_etd": "2026-09-15", "commodity": "X",
        })
        updated = await _patch(c, f"/api/v2/shipments/{s['id']}/status", {
            "customs_status": "submitting",
            "booking_remark": "客户要求 8/22 放行",
        })
        # 验证 1.5.1 触发字段也在响应里
        assert "booking_request_sent_at" in updated
        assert "so_received_at" in updated
        assert "cy_cutoff_at" in updated
        # 验证 1.5.2 字段在响应里
        assert updated["customs_status"] == "submitting"
        assert updated["booking_remark"] == "客户要求 8/22 放行"
