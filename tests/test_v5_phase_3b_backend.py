"""v0.5 阶段 3 第二批后端测试:
- GET /api/v2/exceptions/ - 全局异常列表
- GET /api/v2/exceptions/summary - 异常分布统计
- GET /api/v2/dashboard/kpi - 运营 KPI
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.operational_exception import (
    ExceptionCode,
    ExceptionSeverity,
    ExceptionStatus,
    OperationalException,
)
from app.models.partner import Partner
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


async def _post(client, path, json=None, headers=None):
    r = await client.post(path, json=json or {}, headers=headers or {})
    assert r.status_code in (200, 201), f"{path}: {r.status_code} {r.text}"
    return r.json()


async def _seed_opex(ship_id: str, code: ExceptionCode, severity: ExceptionSeverity,
                      status: ExceptionStatus = ExceptionStatus.OPEN,
                      days_ago: int = 5) -> None:
    async with AsyncSessionLocal() as db:
        ex = OperationalException(
            organization_id=(await db.execute(
                select(Shipment).where(Shipment.id == ship_id)
            )).scalar_one().organization_id,
            shipment_id=ship_id,
            code=code,
            severity=severity,
            status=status,
            detected_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            detected_by="system",
        )
        db.add(ex)
        await db.commit()


# ========== /exceptions/ 全局列表 ==========


@pytest.mark.asyncio
async def test_exceptions_list_empty() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/exceptions/")
        assert r.status_code == 200
        assert r.json() == []


@pytest.mark.asyncio
async def test_exceptions_list_cross_shipment() -> None:
    """全局异常列表 (跨 shipment)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s1 = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "A",
        })
        s2 = await _post(c, "/api/v2/shipments/", {
            "pol": "CNNGB", "pod": "DEHAM", "target_etd": "2026-09-20", "commodity": "B",
        })
        await _seed_opex(s1["id"], ExceptionCode.CUTOFF_APPROACHING, ExceptionSeverity.WARNING)
        await _seed_opex(s2["id"], ExceptionCode.SI_OVERDUE, ExceptionSeverity.CRITICAL)

        r = await c.get("/api/v2/exceptions/")
        items = r.json()
        assert len(items) == 2
        codes = {i["code"] for i in items}
        assert "cutoff_approaching" in codes
        assert "si_overdue" in codes


@pytest.mark.asyncio
async def test_exceptions_list_filter_status_severity() -> None:
    """按 status / severity 过滤."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "A",
        })
        await _seed_opex(s["id"], ExceptionCode.CUTOFF_APPROACHING, ExceptionSeverity.WARNING,
                         status=ExceptionStatus.OPEN)
        await _seed_opex(s["id"], ExceptionCode.SI_OVERDUE, ExceptionSeverity.CRITICAL,
                         status=ExceptionStatus.RESOLVED)
        await _seed_opex(s["id"], ExceptionCode.VGM_OVERDUE, ExceptionSeverity.INFO,
                         status=ExceptionStatus.OPEN)

        # status=open 过滤
        r = await c.get("/api/v2/exceptions/", params={"status": "open"})
        items = r.json()
        assert len(items) == 2
        assert all(i["status"] == "open" for i in items)

        # severity=critical 过滤
        r = await c.get("/api/v2/exceptions/", params={"severity": "critical"})
        items = r.json()
        assert len(items) == 1
        assert items[0]["code"] == "si_overdue"

        # code 过滤
        r = await c.get("/api/v2/exceptions/", params={"code": "cutoff_approaching"})
        items = r.json()
        assert len(items) == 1
        assert items[0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_exceptions_list_days_window() -> None:
    """days 窗口过滤."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "A",
        })
        await _seed_opex(s["id"], ExceptionCode.CUTOFF_APPROACHING, ExceptionSeverity.WARNING,
                         days_ago=5)
        await _seed_opex(s["id"], ExceptionCode.SI_OVERDUE, ExceptionSeverity.CRITICAL,
                         days_ago=60)  # 60 天前

        r = await c.get("/api/v2/exceptions/", params={"days": 30})
        items = r.json()
        # 只返 30 天内的 → 1 个
        assert len(items) == 1
        assert items[0]["code"] == "cutoff_approaching"

        r = await c.get("/api/v2/exceptions/", params={"days": 90})
        items = r.json()
        assert len(items) == 2


# ========== /exceptions/summary ==========


@pytest.mark.asyncio
async def test_exceptions_summary_counts_and_distribution() -> None:
    """异常 summary: 总览 + by_code + by_severity + 解决率."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "A",
        })
        # 3 open + 1 resolved + 1 auto_closed
        await _seed_opex(s["id"], ExceptionCode.CUTOFF_APPROACHING, ExceptionSeverity.WARNING)
        await _seed_opex(s["id"], ExceptionCode.SI_OVERDUE, ExceptionSeverity.CRITICAL)
        await _seed_opex(s["id"], ExceptionCode.VGM_OVERDUE, ExceptionSeverity.INFO)
        await _seed_opex(s["id"], ExceptionCode.CUTOFF_PASSED, ExceptionSeverity.CRITICAL,
                         status=ExceptionStatus.RESOLVED)
        await _seed_opex(s["id"], ExceptionCode.PORT_CHANGED, ExceptionSeverity.WARNING,
                         status=ExceptionStatus.AUTO_CLOSED)

        r = await c.get("/api/v2/exceptions/summary")
        d = r.json()
        assert d["total_count"] == 5
        assert d["open_count"] == 3
        assert d["resolved_count"] == 1
        assert d["auto_closed_count"] == 1
        # 解决率 = resolved/(resolved+auto_closed) = 1/2 = 0.5 (resolved + auto_closed 当作"结束")
        # 实际: resolution_rate = resolved_count / total_count = 1/5 = 0.2
        assert d["resolution_rate"] == 0.2

        # by_severity
        assert d["by_severity"]["warning"] == 2
        assert d["by_severity"]["critical"] == 2
        assert d["by_severity"]["info"] == 1

        # by_code
        by_code_map = {x["code"]: x for x in d["by_code"]}
        assert by_code_map["cutoff_approaching"]["total"] == 1
        assert by_code_map["cutoff_approaching"]["open"] == 1
        assert by_code_map["cutoff_passed"]["resolved"] == 1


@pytest.mark.asyncio
async def test_exceptions_summary_top_shipments() -> None:
    """异常 summary: by_shipment_top (open 异常最多的 TOP 10)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s1 = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "A",
        })
        s2 = await _post(c, "/api/v2/shipments/", {
            "pol": "CNNGB", "pod": "DEHAM", "target_etd": "2026-09-20", "commodity": "B",
        })
        # s1 2 个, s2 3 个
        await _seed_opex(s1["id"], ExceptionCode.CUTOFF_APPROACHING, ExceptionSeverity.WARNING)
        await _seed_opex(s1["id"], ExceptionCode.SI_OVERDUE, ExceptionSeverity.CRITICAL)
        await _seed_opex(s2["id"], ExceptionCode.CUTOFF_APPROACHING, ExceptionSeverity.WARNING)
        await _seed_opex(s2["id"], ExceptionCode.SI_OVERDUE, ExceptionSeverity.CRITICAL)
        await _seed_opex(s2["id"], ExceptionCode.VGM_OVERDUE, ExceptionSeverity.INFO)

        r = await c.get("/api/v2/exceptions/summary")
        d = r.json()
        assert len(d["by_shipment_top"]) == 2
        # s2 (3 个 open) 排前面
        assert d["by_shipment_top"][0]["open_count"] == 3
        assert d["by_shipment_top"][1]["open_count"] == 2


# ========== /dashboard/kpi ==========


@pytest.mark.asyncio
async def test_kpi_overview() -> None:
    """KPI 总览: total/in_progress/completed/cancelled."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 5 shipments: 2 completed + 1 cancelled + 2 in_progress
        for i in range(2):
            await _post(c, "/api/v2/shipments/", {
                "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": f"A{i}",
            })
        for i in range(2):
            s = await _post(c, "/api/v2/shipments/", {
                "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": f"B{i}",
            })
            await _post(c, f"/api/v2/shipments/{s['id']}/stage", {
                "stage": "completed", "reason": "测试收口完成",
            })
        s_cancelled = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "CANC",
        })
        await _post(c, f"/api/v2/shipments/{s_cancelled['id']}/stage", {
            "stage": "cancelled", "reason": "客户主动取消业务",
        })

        r = await c.get("/api/v2/dashboard/kpi")
        d = r.json()
        assert d["total_shipments"] == 5
        assert d["completed"] == 2
        assert d["cancelled"] == 1
        assert d["in_progress"] == 2
        assert d["cancel_rate"] == 0.2


@pytest.mark.asyncio
async def test_kpi_completeness_fields() -> None:
    """KPI 录入完整度: 按字段填充率."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 建 2 单: 1 完整, 1 缺 customer_name/weight_kg
        await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15",
            "commodity": "FULL", "customer_name": "客户A", "weight_kg": 1000.0, "volume_cbm": 5.0,
        })
        await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15",
            "commodity": "EMPTY",  # 不填 customer_name, weight_kg, volume_cbm
        })

        r = await c.get("/api/v2/dashboard/kpi")
        d = r.json()
        fields = {f["field"]: f for f in d["completeness"]["fields"]}
        # customer_name 1/2 = 0.5
        assert fields["customer_name"]["rate"] == 0.5
        assert fields["customer_name"]["filled"] == 1
        # commodity 必填, 都填了, 1.0
        assert fields["commodity"]["rate"] == 1.0
        assert fields["commodity"]["filled"] == 2
        # avg_rate 在 0-1
        assert 0 <= d["completeness"]["avg_rate"] <= 1


@pytest.mark.asyncio
async def test_kpi_by_customer_route_carrier() -> None:
    """KPI 客户/航线/船公司分布."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for _ in range(3):
            await _post(c, "/api/v2/shipments/", {
                "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15",
                "commodity": "X", "customer_name": "客户A", "current_carrier": "COSCO",
            })
        for _ in range(2):
            await _post(c, "/api/v2/shipments/", {
                "pol": "CNNGB", "pod": "DEHAM", "target_etd": "2026-09-20",
                "commodity": "Y", "customer_name": "客户B", "current_carrier": "MSK",
            })
        await _post(c, "/api/v2/shipments/", {
            "pol": "CNSZX", "pod": "CAVAN", "target_etd": "2026-09-25",
            "commodity": "Z", "current_carrier": "COSCO",
        })

        r = await c.get("/api/v2/dashboard/kpi")
        d = r.json()
        # by_customer TOP 10
        assert d["by_customer"][0]["customer_name"] == "客户A"
        assert d["by_customer"][0]["count"] == 3
        assert d["by_customer"][1]["customer_name"] == "客户B"
        assert d["by_customer"][1]["count"] == 2

        # by_route (按 pol→pod 拼接, count 降序)
        assert d["by_route"][0]["route"] == "CNSHA→USLAX"
        assert d["by_route"][0]["count"] == 3
        assert d["by_route"][1]["route"] == "CNNGB→DEHAM"
        assert d["by_route"][1]["count"] == 2

        # by_carrier
        carrier_map = {c["carrier"]: c["count"] for c in d["by_carrier"]}
        assert carrier_map["COSCO"] == 4
        assert carrier_map["MSK"] == 2


@pytest.mark.asyncio
async def test_kpi_monthly_trend() -> None:
    """KPI 月度趋势 (最近 6 月)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        r = await c.get("/api/v2/dashboard/kpi")
        d = r.json()
        # 至少有一个月数据 (本月 202608)
        assert len(d["monthly_trend"]) >= 1
        # 按月份格式 (YYYYMM) 排序
        for i in range(1, len(d["monthly_trend"])):
            assert d["monthly_trend"][i]["month"] >= d["monthly_trend"][i - 1]["month"]


@pytest.mark.asyncio
async def test_kpi_response_time_p50_p90() -> None:
    """KPI 响应时长: booking_request sent → confirmed."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await _post(c, "/api/v2/shipments/", {
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        # 直接灌 booking_request 有 confirmed_at
        from app.models.booking_request import BookingRequest
        async with AsyncSessionLocal() as db:
            org_id = (await db.execute(
                select(Shipment).where(Shipment.id == s["id"])
            )).scalar_one().organization_id
            sent = datetime(2026, 8, 1, 9, tzinfo=timezone.utc)
            # 3 个 booking_request: 1h, 2h, 24h 响应
            for hours in [1, 2, 24]:
                br = BookingRequest(
                    id=f"kpi_br_{hours}",
                    organization_id=org_id,
                    shipment_id=s["id"],
                    partner_id="placeholder",
                    booking_request_no=f"KPI-BR-{hours}",
                    request_version=1,
                    requested_etd=datetime(2026, 9, 15).date(),
                    requested_pol="CNSHA",
                    requested_pod="USLAX",
                    requested_container_type="40HQ",
                    requested_container_count=1,
                    cargo_snapshot={},
                    status="confirmed",
                    sent_at=sent,
                    confirmed_at=sent + timedelta(hours=hours),
                )
                db.add(br)
            await db.commit()

        r = await c.get("/api/v2/dashboard/kpi")
        d = r.json()
        rt = d["response_time"]
        assert rt["samples"] == 3
        # p50 = 2h (1, 2, 24 -> p50 idx 1)
        assert rt["p50_hours"] == 2.0
        # p90 = 24h
        assert rt["p90_hours"] == 24.0
        # avg = (1+2+24)/3 = 9.0
        assert rt["avg_hours"] == 9.0


@pytest.mark.asyncio
async def test_kpi_response_time_empty() -> None:
    """KPI 响应时长无样本时返 None."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/dashboard/kpi")
        d = r.json()
        rt = d["response_time"]
        assert rt["samples"] == 0
        assert rt["avg_hours"] is None
        assert rt["p50_hours"] is None
        assert rt["p90_hours"] is None


@pytest.mark.asyncio
async def test_kpi_empty_shipments() -> None:
    """KPI 空数据时 defaults OK."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/dashboard/kpi")
        d = r.json()
        assert d["total_shipments"] == 0
        assert d["cancel_rate"] == 0.0
        assert d["completeness"]["avg_rate"] == 0.0
        assert d["by_customer"] == []
        assert d["by_route"] == []
        assert d["by_carrier"] == []
        assert d["response_time"]["samples"] == 0
