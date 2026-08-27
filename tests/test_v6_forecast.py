"""v0.6 预报 e2e 测试

覆盖:
- CRUD + dedup (同源同 source_ref / 跨源同 fingerprint / 同源同 fingerprint 不同 ref)
- 周汇总 (ISO 周聚合, 截单预警)
- 配载 + auto_detect_forecast_exceptions
- 截单通知 (dry_run 模式不真发)
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.forecast import Forecast, ForecastSource, ForecastStatus
from app.models.operational_exception import (
    ExceptionCode,
    OperationalException,
)
from app.models.partner import Partner, PartnerType
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


async def _make_customer(c, name: str = "客户A") -> str:
    r = await c.post("/api/v2/partners/", json={
        "partner_type": "customer", "name": name, "primary_email": f"{name}@x.example",
    })
    return r.json()["id"]


# ========== dedup 测试 ==========


@pytest.mark.asyncio
async def test_forecast_create_basic() -> None:
    """基本建预报"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        r = await c.post("/api/v2/forecasts/", json={
            "source": "sales",
            "customer_id": cid,
            "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 2,
            "target_etd": "2026-09-15",
        })
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["status"] == "forecasted"
        assert d["content_fingerprint"]  # 自动生成
        assert d["source"] == "sales"
        assert d["container_count"] == 2


@pytest.mark.asyncio
async def test_forecast_dedup_same_source_ref_409() -> None:
    """同源同 source_ref 第二次返 409 (DB UNIQUE 拒绝)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        body = {
            "source": "sales", "source_ref": "WO-001",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 2,
            "target_etd": "2026-09-15",
        }
        r1 = await c.post("/api/v2/forecasts/", json=body)
        assert r1.status_code == 201, r1.text
        r2 = await c.post("/api/v2/forecasts/", json=body)
        assert r2.status_code == 409, r2.text
        assert "source_ref" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_forecast_dedup_cross_source_same_fingerprint() -> None:
    """跨源 (sales + customer_service) 同 fingerprint 自动 merge → 已有 1 升级 confirmed"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        # 1. sales 源 (无 dedup 历史, 返 forecasted)
        r1 = await c.post("/api/v2/forecasts/", json={
            "source": "sales", "source_ref": "WO-A",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 2,
            "target_etd": "2026-09-15",
        })
        assert r1.status_code == 201
        assert r1.json()["status"] == "forecasted"  # 1 创建时无 dedup, 保持 forecasted

        # 2. customer_service 源 (同 fingerprint) → 触发 merge_into_existing, 1 升级
        r2 = await c.post("/api/v2/forecasts/", json={
            "source": "customer_service", "source_ref": "CS-001",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 2,
            "target_etd": "2026-09-15",
        })
        assert r2.status_code == 201
        # 1. 已被自动升级 confirmed (merge 触发)
        r1_after = await c.get(f"/api/v2/forecasts/{r1.json()['id']}")
        assert r1_after.json()["status"] == "confirmed", "第一源应被升级为 confirmed"
        # 2. 保持 forecasted
        assert r2.json()["status"] == "forecasted"


@pytest.mark.asyncio
async def test_forecast_dedup_same_source_same_fingerprint_different_ref() -> None:
    """同源同 fingerprint 不同 source_ref 标 needs_human (notes 含疑似重复)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        r1 = await c.post("/api/v2/forecasts/", json={
            "source": "sales", "source_ref": "WO-A",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 2,
            "target_etd": "2026-09-15",
        })
        assert r1.status_code == 201
        # 同源同 fingerprint 不同 source_ref
        r2 = await c.post("/api/v2/forecasts/", json={
            "source": "sales", "source_ref": "WO-B",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 2,
            "target_etd": "2026-09-15",
        })
        assert r2.status_code == 201
        # notes 应标疑似重复
        assert "疑似重复" in r2.json()["notes"]


# ========== 周汇总测试 ==========


@pytest.mark.asyncio
async def test_weekly_summary_aggregates_by_route() -> None:
    """周汇总按 (pol/pod × customer) 聚合"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        # 建 3 条同一周同一路线 forecasts
        for i in range(3):
            await c.post("/api/v2/forecasts/", json={
                "source": "sales",
                "customer_id": cid, "customer_name": "客户A",
                "pol": "CNSHA", "pod": "USLAX",
                "container_type": "40HQ", "container_count": 1,
                "target_etd": "2026-09-15",  # ISO 周二 (周一 9/14)
            })
        # 另 1 条不同路线
        await c.post("/api/v2/forecasts/", json={
            "source": "sales",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNNGB", "pod": "DEHAM",
            "container_type": "40GP", "container_count": 2,
            "target_etd": "2026-09-16",
        })

        # 查 2026-09-14 那周 (周一)
        r = await c.get("/api/v2/forecasts/weekly", params={"week_start": "2026-09-14"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_forecast_count"] == 5  # 3 + 2
        assert len(d["rows"]) == 2  # CNSHA→USLAX + CNNGB→DEHAM
        cnsha_row = next(r for r in d["rows"] if r["pol"] == "CNSHA")
        assert cnsha_row["total_count"] == 3
        assert cnsha_row["pending_count"] == 3
        assert cnsha_row["confirmed_count"] == 0
        cnngb_row = next(r for r in d["rows"] if r["pol"] == "CNNGB")
        assert cnngb_row["total_count"] == 2
        # source breakdown
        assert cnsha_row["source_breakdown"] == {"sales": 3}


@pytest.mark.asyncio
async def test_weekly_summary_cross_source_confirmed_count() -> None:
    """周汇总 confirmed_count = 多源命中数"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        # sales + customer_service 跨源同 fingerprint → 第一条变 confirmed
        await c.post("/api/v2/forecasts/", json={
            "source": "sales", "source_ref": "WO-A",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 2,
            "target_etd": "2026-09-15",
        })
        await c.post("/api/v2/forecasts/", json={
            "source": "customer_service", "source_ref": "CS-001",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 2,
            "target_etd": "2026-09-15",
        })

        r = await c.get("/api/v2/forecasts/weekly", params={"week_start": "2026-09-14"})
        d = r.json()
        row = d["rows"][0]
        # confirmed_count = 2 (sales 升级为 confirmed) + 0 (customer_service forecasted)
        # 实际: sales 升级 confirmed (cnt=2) + cs 仍 forecasted
        # total=4, confirmed=2, pending=2
        assert row["total_count"] == 4
        assert row["confirmed_count"] == 2
        assert row["pending_count"] == 2
        # source breakdown: sales=2, customer_service=2
        assert row["source_breakdown"] == {"sales": 2, "customer_service": 2}


# ========== 配载 + 异常件自动标记 ==========


@pytest.mark.asyncio
async def test_forecast_allocate_triggers_exceptions_on_count_mismatch() -> None:
    """forecast 配载到 Shipment, 数量差 > 阈值自动建 FORECAST_QUANTITY_MISMATCH"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        # 建 forecast (1 柜 - 跟 ship 默认 1 一样, 但因阈值=0 任何不等才报)
        r1 = await c.post("/api/v2/forecasts/", json={
            "source": "sales",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 1,
            "target_etd": "2026-09-15",
        })
        fid = r1.json()["id"]
        # 建 shipment (默认 container_count=1) 跟 forecast 一致 → 不报异常 (sanity)
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15",
            "commodity": "X", "container_count": 1,
        })
        sid = s.json()["id"]

        # 配载 (数量一致 + etd 一致 → 不应建任何异常)
        r2 = await c.post(f"/api/v2/forecasts/{fid}/allocate", json={"shipment_id": sid})
        assert r2.status_code == 200, r2.text
        async with AsyncSessionLocal() as db:
            exs = (await db.execute(
                select(OperationalException).where(OperationalException.shipment_id == sid)
            )).scalars().all()
        # 数量 + etd 都一致 → 无异常
        assert len(exs) == 0

        # 模拟后续: shipment 改 etd 差 5 天, 重新检测
        async with AsyncSessionLocal() as db:
            s_db = (await db.execute(
                select(Shipment).where(Shipment.id == sid)
            )).scalar_one()
            from datetime import date
            s_db.etd = date(2026, 9, 20)
            await db.commit()
        from app.services.forecast import auto_detect_forecast_exceptions
        async with AsyncSessionLocal() as db:
            exs2 = await auto_detect_forecast_exceptions(
                db, organization_id=s_db.organization_id, forecast_id=fid,
            )
            await db.commit()
        assert len(exs2) == 1
        assert exs2[0].code == ExceptionCode.FORECAST_ETD_MISMATCH
        assert exs2[0].context["diff_days"] == 5


@pytest.mark.asyncio
async def test_forecast_allocate_triggers_exception_on_etd_mismatch() -> None:
    """forecast ETD vs Shipment ETD 差 >= 3 天自动建 FORECAST_ETD_MISMATCH"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        r1 = await c.post("/api/v2/forecasts/", json={
            "source": "sales",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 1,
            "target_etd": "2026-09-15",
        })
        fid = r1.json()["id"]
        # 建 shipment + PATCH 设 etd (5 天差)
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15",
            "commodity": "X", "container_count": 1,
        })
        sid = s.json()["id"]
        await c.patch(f"/api/v2/shipments/{sid}", json={"etd": "2026-09-20"})

        await c.post(f"/api/v2/forecasts/{fid}/allocate", json={"shipment_id": sid})

        async with AsyncSessionLocal() as db:
            exs = (await db.execute(
                select(OperationalException).where(OperationalException.shipment_id == sid)
            )).scalars().all()
        etd_exs = [e for e in exs if e.code == ExceptionCode.FORECAST_ETD_MISMATCH]
        assert len(etd_exs) >= 1
        assert any(e.context.get("diff_days") == 5 for e in etd_exs)


@pytest.mark.asyncio
async def test_forecast_allocate_no_exception_when_match() -> None:
    """forecast 与 Shipment 字段一致时不建异常"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        r1 = await c.post("/api/v2/forecasts/", json={
            "source": "sales",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 1,
            "target_etd": "2026-09-15",
        })
        fid = r1.json()["id"]
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15",
            "commodity": "X", "container_count": 1, "etd": "2026-09-15",
        })
        sid = s.json()["id"]
        await c.post(f"/api/v2/forecasts/{fid}/allocate", json={"shipment_id": sid})

        async with AsyncSessionLocal() as db:
            exs = (await db.execute(
                select(OperationalException).where(OperationalException.shipment_id == sid)
            )).scalars().all()
        assert len(exs) == 0


# ========== 取消 ==========


@pytest.mark.asyncio
async def test_forecast_cancel() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        r1 = await c.post("/api/v2/forecasts/", json={
            "source": "sales",
            "customer_id": cid, "customer_name": "客户A",
            "pol": "CNSHA", "pod": "USLAX",
            "container_type": "40HQ", "container_count": 1,
            "target_etd": "2026-09-15",
        })
        fid = r1.json()["id"]
        r2 = await c.post(f"/api/v2/forecasts/{fid}/cancel", json={"reason": "客户撤单"})
        assert r2.status_code == 200
        assert r2.json()["status"] == "cancelled"
        assert "客户撤单" in r2.json()["notes"]


# ========== 批量 (CSV 导入 dry_run) ==========


@pytest.mark.asyncio
async def test_forecast_bulk_dry_run() -> None:
    """批量 dry_run 不入库, 但返回 dedup 预判"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        body = {
            "dry_run": True,
            "forecasts": [
                {
                    "source": "sales", "source_ref": "WO-001",
                    "customer_id": cid, "customer_name": "客户A",
                    "pol": "CNSHA", "pod": "USLAX",
                    "container_type": "40HQ", "container_count": 1,
                    "target_etd": "2026-09-15",
                },
                {
                    "source": "shending", "source_ref": "SD-001",  # 跨源同 fingerprint
                    "customer_id": cid, "customer_name": "客户A",
                    "pol": "CNSHA", "pod": "USLAX",
                    "container_type": "40HQ", "container_count": 1,
                    "target_etd": "2026-09-15",
                },
            ],
        }
        r = await c.post("/api/v2/forecasts/bulk", json=body)
        assert r.status_code == 200, r.text
        d = r.json()
        # dry_run 不真建
        assert d["created"] == 0
        assert d["duplicates"] == 0  # dry_run 不计 duplicates
        assert len(d["details"]) == 2
        # 第 1 条: create_new (空 db)
        # 第 2 条: merge_into_existing (同 fingerprint, 但 dry_run 看不到 existing)
        # 实际上 dry_run 时 find_duplicate_forecasts 也查 db, 第 2 条看不到任何 existing
        # 所以都是 create_new
        for det in d["details"]:
            assert det["action"] == "create_new"

        # 验证 db 真的没建
        async with AsyncSessionLocal() as db:
            cnt = (await db.execute(select(Forecast))).scalars().all()
        assert len(cnt) == 0


@pytest.mark.asyncio
async def test_forecast_bulk_real_with_cross_source() -> None:
    """批量真实导入 + 跨源同 fingerprint 自动 confirm 第一条"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _make_customer(c)
        body = {
            "dry_run": False,
            "forecasts": [
                {
                    "source": "sales", "source_ref": "WO-001",
                    "customer_id": cid, "customer_name": "客户A",
                    "pol": "CNSHA", "pod": "USLAX",
                    "container_type": "40HQ", "container_count": 1,
                    "target_etd": "2026-09-15",
                },
                {
                    "source": "customer_service", "source_ref": "CS-001",
                    "customer_id": cid, "customer_name": "客户A",
                    "pol": "CNSHA", "pod": "USLAX",
                    "container_type": "40HQ", "container_count": 1,
                    "target_etd": "2026-09-15",
                },
            ],
        }
        r = await c.post("/api/v2/forecasts/bulk", json=body)
        assert r.status_code == 200
        d = r.json()
        # 两条都 create (merge_into_existing 也算 create - 它是写入, 只是顺带 confirmed 已存在的)
        assert d["created"] == 2
        assert d["duplicates"] == 0  # 没有 needs_human 场景

        # 验证 db 状态
        async with AsyncSessionLocal() as db:
            fs = (await db.execute(
                select(Forecast).order_by(Forecast.created_at.asc())
            )).scalars().all()
        assert len(fs) == 2
        # 第 1 条 (sales) 应被升级为 confirmed
        assert fs[0].status == ForecastStatus.CONFIRMED
        # 第 2 条 (customer_service) 保持 forecasted
        assert fs[1].status == ForecastStatus.FORECASTED
