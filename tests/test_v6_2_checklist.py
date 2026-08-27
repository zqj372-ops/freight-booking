"""v0.6.2 清单复核 e2e 测试

覆盖:
1. 启动复核 → 14 项跑完, 包含 pass/warning/critical
2. 复核历史列表
3. 详情查询
4. acknowledge item (warning 强制 pass)
5. signoff 整个复核
6. 重复 signoff 返 400
7. critical 项自动建 OperationalException (打通 v0.6.1 AI 跟进)
8. 不同 review_type (pre_load/pre_cutoff/random) 都跑通
9. 已建 Container (含柜号封条) → pass 项多
10. status 过滤
11. invalid status 返 400
12. 404 路径
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.checklist import (
    ChecklistItem,
    ChecklistReview,
    ChecklistReviewStatus,
    ChecklistItemCategory,
    ChecklistItemCode,
    ChecklistSeverity,
)
from app.models.container import Container, ContainerStatus
from app.models.operational_exception import (
    OperationalException,
    ExceptionStatus,
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


async def _make_shipment(c, **overrides) -> str:
    body = {
        "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15",
        "commodity": "X", "container_count": 1, "container_type": "40HQ",
    }
    body.update(overrides)
    s = await c.post("/api/v2/shipments/", json=body)
    assert s.status_code == 201, s.text
    return s.json()["id"]


async def _add_container(c: AsyncClient, shipment_id: str, container_no: str = "MSCU1234567", seal_no: str | None = None) -> str:
    """v0.5 ship 创建自动建 Container, 这里 PATCH 填柜号封条"""
    conts = (await c.get(f"/api/v2/shipments/{shipment_id}/containers")).json()
    cid = conts[0]["id"]
    body = {"container_no": container_no}
    if seal_no:
        body["seal_no"] = seal_no
    r = await c.patch(f"/api/v2/containers/{cid}", json=body)
    assert r.status_code == 200, r.text
    return cid


# ========== 1. 启动复核 → 14 项 ==========


@pytest.mark.asyncio
async def test_start_checklist_runs_14_items() -> None:
    """建空 shipment (无 Container 无 Document) → 跑出 14 项, critical=2 (缺柜号封条), warning=4 (4 文件)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={
            "review_type": "random",
            "trigger_reason": "test",
        })
        assert r.status_code == 201
        j = r.json()
        assert j["total_items"] == 14
        assert j["passed_items"] == 8
        assert j["warning_items"] == 4
        assert j["critical_items"] == 2
        assert j["overall_severity"] == "critical"
        assert j["status"] == "draft"


# ========== 2. 复核历史列表 ==========


@pytest.mark.asyncio
async def test_list_reviews() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        for i in range(2):
            r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": "random"})
            assert r.status_code == 201

        r2 = await c.get(f"/api/v2/shipments/{sid}/checklist-reviews")
        assert r2.status_code == 200
        assert len(r2.json()) == 2


# ========== 3. 详情查询 ==========


@pytest.mark.asyncio
async def test_get_review_detail() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": "random"})
        rid = r.json()["id"]
        r2 = await c.get(f"/api/v2/checklist-reviews/{rid}")
        assert r2.status_code == 200
        assert len(r2.json()["items"]) == 14


# ========== 4. acknowledge item (warning 强制 pass) ==========


@pytest.mark.asyncio
async def test_acknowledge_warning_item_marks_pass() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": "random"})
        rid = r.json()["id"]
        # 找 SI_MISSING warning 项
        warning_item = next(
            (i for i in r.json()["items"] if i["code"] == "si_missing"), None,
        )
        assert warning_item is not None
        assert warning_item["severity"] == "warning"

        r2 = await c.post(
            f"/api/v2/checklist-reviews/{rid}/items/{warning_item['id']}/ack",
            json={"note": "稍后补传"},
        )
        assert r2.status_code == 200
        assert r2.json()["match"] is True  # warning 强制 pass
        assert r2.json()["acknowledged_at"] is not None


# ========== 5. signoff 整个复核 ==========


@pytest.mark.asyncio
async def test_signoff_review() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": "random"})
        rid = r.json()["id"]

        r2 = await c.post(f"/api/v2/checklist-reviews/{rid}/signoff", json={"note": "已知问题, 决定发船"})
        assert r2.status_code == 200
        assert r2.json()["status"] == "signed_off"
        assert r2.json()["signed_off_at"] is not None
        assert "已知问题" in (r2.json()["note"] or "")


# ========== 6. 重复 signoff 返 400 ==========


@pytest.mark.asyncio
async def test_double_signoff_returns_400() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": "random"})
        rid = r.json()["id"]
        await c.post(f"/api/v2/checklist-reviews/{rid}/signoff", json={})
        r2 = await c.post(f"/api/v2/checklist-reviews/{rid}/signoff", json={})
        assert r2.status_code == 400


# ========== 7. critical 项自动建 OperationalException ==========


@pytest.mark.asyncio
async def test_critical_items_auto_create_exceptions() -> None:
    """缺柜号/缺封条 → critical → 自动建 OperationalException (MISSING_CONTAINER_NO/MISSING_SEAL_NO)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": "random"})
        rid = r.json()["id"]
        # related_exception_ids 应该有值 (2 个 critical 映射到异常)
        assert r.json()["related_exception_ids"] is not None
        assert len(r.json()["related_exception_ids"]) >= 1

        # 验证异常在数据库
        async with AsyncSessionLocal() as db:
            exs = (await db.execute(
                select(OperationalException).where(OperationalException.shipment_id == sid)
            )).scalars().all()
        assert len(exs) >= 1
        codes = {ex.code.value for ex in exs}
        # 至少有缺柜号或缺封条
        assert "missing_container_no" in codes or "missing_seal_no" in codes


# ========== 8. 不同 review_type 都跑通 ==========


@pytest.mark.asyncio
async def test_all_review_types() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        for rt in ["pre_load", "pre_cutoff", "pre_departure", "random"]:
            r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": rt})
            assert r.status_code == 201
            assert r.json()["review_type"] == rt


# ========== 9. 已建 Container (含柜号封条) → pass 多 ==========


@pytest.mark.asyncio
async def test_with_container_more_pass_items() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        # 先建 Container (含柜号封条)
        await _add_container(c, sid, container_no="MSCU1234567", seal_no="SEAL001")

        r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": "random"})
        j = r.json()
        # critical 应该 0 (柜号封条都填了)
        # 但 SI/VGM/CI/PL 还是没传 → warning=4
        assert j["critical_items"] == 0
        assert j["warning_items"] == 4
        assert j["overall_severity"] == "warning"  # 没 critical 时, 有 warning 就是 warning
        # pass 应该 10 (8 + 2: 柜号 + 封条)
        assert j["passed_items"] == 10


# ========== 10. status 过滤 ==========


@pytest.mark.asyncio
async def test_list_reviews_with_status_filter() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r1 = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": "random"})
        rid = r1.json()["id"]
        await c.post(f"/api/v2/checklist-reviews/{rid}/signoff", json={})

        r2 = await c.get(f"/api/v2/shipments/{sid}/checklist-reviews?status=signed_off")
        assert r2.status_code == 200
        assert len(r2.json()) == 1
        assert r2.json()[0]["status"] == "signed_off"

        r3 = await c.get(f"/api/v2/shipments/{sid}/checklist-reviews?status=draft")
        assert len(r3.json()) == 0


# ========== 11. invalid status 返 400 ==========


@pytest.mark.asyncio
async def test_invalid_status_filter_400() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r = await c.get(f"/api/v2/shipments/{sid}/checklist-reviews?status=invalid")
        assert r.status_code == 400


# ========== 12. 404 路径 ==========


@pytest.mark.asyncio
async def test_get_review_404() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/checklist-reviews/nonexistent-id")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_start_checklist_404_for_missing_shipment() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v2/shipments/nonexistent-id/checklist-reviews", json={"review_type": "random"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_acknowledge_404_for_missing_item() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        r = await c.post(f"/api/v2/shipments/{sid}/checklist-reviews", json={"review_type": "random"})
        rid = r.json()["id"]
        r2 = await c.post(
            f"/api/v2/checklist-reviews/{rid}/items/nonexistent/ack",
            json={},
        )
        assert r2.status_code == 404
