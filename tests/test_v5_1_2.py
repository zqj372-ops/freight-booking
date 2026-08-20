"""v0.5 阶段 1.2 测试 - 业务聚合 (Shipment + BookingRequest + BookingConfirmation + Container)"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta, timezone
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.organization_context import DEFAULT_ORG_SLUG
from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models import (
    BookingConfirmation,
    BookingRequest,
    Container,
    Organization,
    Partner,
    Shipment,
)


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


async def _create_partner(client: AsyncClient, partner_type: str, name: str, **kw) -> dict:
    r = await client.post(
        "/api/v2/partners/",
        json={"partner_type": partner_type, "name": name, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_create_shipment_auto_container() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        customer = await _create_partner(c, "customer", "ACME Corp")
        s = (await c.post(
            "/api/v2/shipments/",
            json={
                "customer_partner_id": customer["id"],
                "pol": "CNSHA",
                "pod": "USLAX",
                "target_etd": "2026-09-15",
                "commodity": "ELECTRONIC PARTS",
                "weight_kg": 12000,
                "volume_cbm": 25.5,
            },
        )).json()
        assert s["job_no"].startswith("FB-")
        assert s["stage"] == "draft"
        assert s["container_count"] == 1

        # 查 container tab
        containers = (await c.get(f"/api/v2/shipments/{s['id']}/containers")).json()
        assert len(containers) == 1
        assert containers[0]["container_no"] is None
        assert containers[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_shipment_stage_change_audit() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = (await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()

        # 手动改 stage
        r = await c.post(f"/api/v2/shipments/{s['id']}/stage", json={
            "stage": "booking_in_progress",
            "reason": "客户要求立即发订舱",
        })
        assert r.status_code == 200
        assert r.json()["stage"] == "booking_in_progress"

        # 查 audit
        logs = (await c.get(f"/api/v2/audit-logs/by-entity/shipment/{s['id']}")).json()
        actions = [l["action"] for l in logs]
        assert "create" in actions
        assert "stage_change" in actions
        sc_log = next(l for l in logs if l["action"] == "stage_change")
        assert sc_log["field_changes"]["stage"]["new"] == "booking_in_progress"
        assert sc_log["reason"] == "客户要求立即发订舱"

        # 改回 draft
        r = await c.post(f"/api/v2/shipments/{s['id']}/stage", json={
            "stage": "cancelled",
            "reason": "客户最终取消此票",
        })
        assert r.status_code == 200
        assert r.json()["stage"] == "cancelled"
        assert r.json()["cancellation_reason"] == "客户最终取消此票"
        assert r.json()["cancelled_at"] is not None

        # 终态: 不能 update
        r = await c.patch(f"/api/v2/shipments/{s['id']}", json={"remark": "x"})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_booking_request_full_lifecycle() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        customer = await _create_partner(c, "customer", "ACME")
        agent = await _create_partner(c, "agent_l1", "代理 A", short_code="AGT-A", response_sla_hours=24)

        s = (await c.post("/api/v2/shipments/", json={
            "customer_partner_id": customer["id"],
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()

        # 创建 BR v1
        br1 = (await c.post("/api/v2/booking-requests/", json={
            "shipment_id": s["id"],
            "partner_id": agent["id"],
            "requested_etd": "2026-09-15",
            "requested_pol": "CNSHA",
            "requested_pod": "USLAX",
            "requested_container_type": "40HQ",
        })).json()
        assert br1["booking_request_no"] == "BR-001"
        assert br1["request_version"] == 1
        assert br1["status"] == "draft"
        assert br1["cargo_snapshot"]["pol"] == "CNSHA"
        assert br1["response_sla_hours"] == 24  # 来自 partner

        # 发送 (dry_run)
        r = await c.post(f"/api/v2/booking-requests/{br1['id']}/send", json={
            "template_code": "booking_request",
            "to_emails": ["booking@agt-a.com"],
            "cc_emails": [],
            "dry_run": True,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "draft"  # dry_run 不改状态

        # 实际发送 (P1#3 修复: SMTP 未配时返 502, BR 保持 draft)
        r = await c.post(f"/api/v2/booking-requests/{br1['id']}/send", json={
            "template_code": "booking_request",
            "to_emails": ["booking@agt-a.com"],
            "cc_emails": [],
            "dry_run": False,
        })
        # 测试环境 SMTP 未配, 应该返 502, BR 不动
        assert r.status_code == 502
        assert "邮件" in r.json()["detail"] or "SMTP" in r.json()["detail"]
        # 重新查 BR 状态
        r2 = await c.get(f"/api/v2/booking-requests/{br1['id']}")
        assert r2.json()["status"] == "draft"
        assert r2.json()["sent_at"] is None

        # 改 ETD → 创建 BR v2 (supersedes v1)
        br2 = (await c.post("/api/v2/booking-requests/", json={
            "shipment_id": s["id"],
            "partner_id": agent["id"],
            "requested_etd": "2026-09-18",  # 改了
            "requested_pol": "CNSHA",
            "requested_pod": "USLAX",
            "requested_container_type": "40HQ",
            "supersedes_id": br1["id"],
        })).json()
        assert br2["booking_request_no"] == "BR-002"
        assert br2["request_version"] == 2
        assert br2["supersedes_id"] == br1["id"]


@pytest.mark.asyncio
async def test_booking_confirmation_accept_writes_to_shipment() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        customer = await _create_partner(c, "customer", "ACME")
        agent = await _create_partner(c, "agent_l1", "代理 A")
        s = (await c.post("/api/v2/shipments/", json={
            "customer_partner_id": customer["id"],
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()
        br = (await c.post("/api/v2/booking-requests/", json={
            "shipment_id": s["id"], "partner_id": agent["id"],
            "requested_etd": "2026-09-15", "requested_pol": "CNSHA", "requested_pod": "USLAX",
            "requested_container_type": "40HQ",
        })).json()

        # 收到 BC v1
        bc1 = (await c.post("/api/v2/booking-confirmations/", json={
            "shipment_id": s["id"],
            "booking_request_id": br["id"],
            "carrier": "MAERSK",
            "carrier_booking_no": "MAE1234567",
            "vessel_name": "MAERSK HONG KONG",
            "voyage_no": "V.345E",
            "pol": "CNSHA", "pod": "USLAX",
            "etd": "2026-09-15", "eta": "2026-10-05",
            "cy_open_at": "2026-09-10T08:00:00Z",
            "si_cutoff_at": "2026-09-13T17:00:00Z",
            "vgm_cutoff_at": "2026-09-13T17:00:00Z",
            "cy_cutoff_at": "2026-09-14T18:00:00Z",
            "container_type": "40HQ",
            "container_count": 1,
        })).json()
        assert bc1["version"] == 1
        assert bc1["is_current"] is True
        assert bc1["status"] == "matched_pending"

        # 接受
        r = await c.post(f"/api/v2/booking-confirmations/{bc1['id']}/accept", json={
            "reason": "船期和柜型与申请一致, 接受",
        })
        assert r.status_code == 200
        bc1_after = r.json()
        assert bc1_after["status"] == "accepted"
        assert bc1_after["is_current"] is True
        assert bc1_after["review_status"] == "reviewed"

        # Shipment 字段被写入
        s_after = (await c.get(f"/api/v2/shipments/{s['id']}")).json()
        assert s_after["stage"] == "booked"
        assert s_after["carrier_booking_no"] == "MAE1234567"
        assert s_after["current_carrier"] == "MAERSK"
        assert s_after["etd"] == "2026-09-15"
        assert s_after["eta"] == "2026-10-05"


@pytest.mark.asyncio
async def test_booking_confirmation_version_supersede() -> None:
    """客户改 ETD, 收 BC v2, v1 自动 superseded, is_current 切换"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        customer = await _create_partner(c, "customer", "ACME")
        agent = await _create_partner(c, "agent_l1", "代理 A")
        s = (await c.post("/api/v2/shipments/", json={
            "customer_partner_id": customer["id"],
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()

        # BC v1
        bc1 = (await c.post("/api/v2/booking-confirmations/", json={
            "shipment_id": s["id"], "carrier": "MAERSK",
            "etd": "2026-09-15", "eta": "2026-10-05",
        })).json()
        await c.post(f"/api/v2/booking-confirmations/{bc1['id']}/accept", json={"reason": "船期 OK 接受 v1"})

        # BC v2 (改时间)
        bc2 = (await c.post("/api/v2/booking-confirmations/", json={
            "shipment_id": s["id"], "carrier": "MAERSK",
            "etd": "2026-09-18", "eta": "2026-10-08",
        })).json()
        assert bc2["version"] == 2
        # P1#4 修复: v1 已 accepted + v2 received (未审核) 时, v2 不应 is_current=True
        assert bc2["is_current"] is False, "v2 不应 is_current (v1 已 accepted)"

        # 接受 v2
        await c.post(f"/api/v2/booking-confirmations/{bc2['id']}/accept", json={"reason": "船期改期, 接受 v2"})

        # v1 应该被 superseded
        bc1_after = (await c.get(f"/api/v2/booking-confirmations/{bc1['id']}")).json()
        assert bc1_after["status"] == "superseded"
        assert bc1_after["is_current"] is False
        assert bc1_after["supersedes_id"] == bc2["id"]

        # v2 是 current
        bc2_after = (await c.get(f"/api/v2/booking-confirmations/{bc2['id']}")).json()
        assert bc2_after["status"] == "accepted"
        assert bc2_after["is_current"] is True

        # Shipment etd 应该被 v2 覆盖
        s_after = (await c.get(f"/api/v2/shipments/{s['id']}")).json()
        assert s_after["etd"] == "2026-09-18"


@pytest.mark.asyncio
async def test_container_pickup_status_auto() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = (await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()
        containers = (await c.get(f"/api/v2/shipments/{s['id']}/containers")).json()
        cid = containers[0]["id"]

        # 录入柜号 + 提柜时间
        pickup_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = await c.patch(f"/api/v2/containers/{cid}", json={
            "container_no": "MSKU1234567",
            "seal_no": "SEAL-001",
            "pickup_location": "上海外高桥",
            "pickup_time": pickup_time,
        })
        assert r.status_code == 200
        c_after = r.json()
        assert c_after["container_no"] == "MSKU1234567"
        assert c_after["seal_no"] == "SEAL-001"
        assert c_after["status"] == "picked_up"  # 自动推导

        # 录入装船时间
        loaded_time = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        r = await c.patch(f"/api/v2/containers/{cid}", json={
            "loaded_time": loaded_time,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "loaded"  # 再次自动推导


@pytest.mark.asyncio
async def test_job_no_daily_reset() -> None:
    """今天创的 job_no 应该递增, 不重置 (但今天只 2 个)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s1 = (await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()
        s2 = (await c.post("/api/v2/shipments/", json={
            "pol": "CNNGB", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()
        # 同一天, 流水递增
        assert s1["job_no"].endswith("-0001")
        assert s2["job_no"].endswith("-0002")
        # 解析格式
        from app.services.numbering import parse_job_no
        p1 = parse_job_no(s1["job_no"])
        assert p1["prefix"] == "FB"
        assert p1["seq"] == 1
        p2 = parse_job_no(s2["job_no"])
        assert p2["seq"] == 2


@pytest.mark.asyncio
async def test_compute_diff_helper() -> None:
    from app.services.numbering import compute_diff
    requested = {"pol": "CNSHA", "target_etd": "2026-09-01", "container_count": 1}
    confirmed = {"pol": "CNSHA", "target_etd": "2026-09-02", "container_count": 1}
    diff = compute_diff(requested, confirmed)
    assert diff["pol"]["match"] is True
    assert diff["target_etd"]["match"] is False
    assert diff["target_etd"]["delta_days"] == 1
    assert diff["container_count"]["match"] is True


@pytest.mark.asyncio
async def test_shipment_list_filter() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 建 3 单
        for i in range(3):
            await c.post("/api/v2/shipments/", json={
                "pol": "CNSHA" if i % 2 == 0 else "CNNGB",
                "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
            })
        # 全部
        all_s = (await c.get("/api/v2/shipments/")).json()
        assert len(all_s) == 3
        # 按 pol
        cn = (await c.get("/api/v2/shipments/?pol=CNSHA")).json()
        assert len(cn) == 2
        # 搜索
        sr = (await c.get("/api/v2/shipments/?search=FB-")).json()
        assert len(sr) == 3
