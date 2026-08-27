"""v0.6.1 异常 AI 跟进 e2e 测试

覆盖:
1. 创建异常 → 自动 enqueue 3 个 fetch job + 1 个初始 update
2. timeline endpoint 返回完整结构
3. fetch-now 立即触发 → 产生 ai_summary / ai_suggestion update
4. add_update (user_note) → 1 条 user_note update
5. add_update (accept_ai_suggestion=True) → 异常 resolved + 3 条新 update
6. ai-question 问答 → 返回 mock answer
7. fetch jobs 列表 + 状态过滤
8. accept-suggestion 快捷 → 异常 close
9. 已 resolved 异常的 fetch-now 跳过
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.exception_update import (
    ExceptionFetchJob,
    ExceptionFetchJobStatus,
    ExceptionUpdate,
    ExceptionUpdateType,
)
from app.models.operational_exception import (
    ExceptionCode,
    ExceptionSeverity,
    ExceptionStatus,
    OperationalException,
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
        "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15",
        "commodity": "X", "container_count": 1,
    })
    assert s.status_code == 201, s.text
    return s.json()["id"]


async def _make_exception(c, shipment_id: str, code: str = "schedule_changed", severity: str = "warning") -> str:
    r = await c.post(f"/api/v2/workflow/shipments/{shipment_id}/exceptions", json={
        "code": code,
        "severity": severity,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ========== 1. 创建异常自动 enqueue ==========


@pytest.mark.asyncio
async def test_create_exception_auto_enqueue_3_jobs() -> None:
    """建异常 → 自动建 3 个 fetch job (carrier/email/wechat) + 1 个 STATUS_CHANGE update"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        ex_id = await _make_exception(c, sid)

        async with AsyncSessionLocal() as db:
            jobs = (await db.execute(
                select(ExceptionFetchJob).where(ExceptionFetchJob.exception_id == ex_id)
            )).scalars().all()
            assert len(jobs) == 3
            sources = {j.source.value for j in jobs}
            assert sources == {"carrier_website", "email", "wechat"}
            # status 都 PENDING, next_run_at 已设
            for j in jobs:
                assert j.status == ExceptionFetchJobStatus.PENDING
                assert j.next_run_at is not None
                assert j.run_count == 0
                assert j.max_runs == 84  # 7 天 × 12 次/天

            # 1 个初始 STATUS_CHANGE update
            updates = (await db.execute(
                select(ExceptionUpdate).where(ExceptionUpdate.exception_id == ex_id)
            )).scalars().all()
            assert len(updates) == 1
            assert updates[0].update_type == ExceptionUpdateType.STATUS_CHANGE
            assert "AI 跟进已启动" in updates[0].summary


# ========== 2. timeline endpoint ==========


@pytest.mark.asyncio
async def test_timeline_endpoint() -> None:
    """GET /exceptions/{id}/timeline 返回完整结构"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        ex_id = await _make_exception(c, sid)

        r = await c.get(f"/api/v2/exceptions/{ex_id}/timeline")
        assert r.status_code == 200
        tl = r.json()
        assert tl["exception_id"] == ex_id
        assert tl["shipment_id"] == sid
        assert tl["code"] == "schedule_changed"
        assert tl["severity"] == "warning"
        assert tl["status"] == "open"
        assert len(tl["updates"]) == 1
        assert len(tl["fetch_jobs"]) == 3
        # 没跑过 AI, latest_ai_suggestion 应为 None
        assert tl["latest_ai_suggestion"] is None


# ========== 3. fetch-now 立即触发 ==========


@pytest.mark.asyncio
async def test_fetch_now_creates_ai_updates() -> None:
    """POST /fetch-now 立即跑, 至少产生 ai_summary + ai_suggestion update"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        ex_id = await _make_exception(c, sid)

        r = await c.post(f"/api/v2/exceptions/{ex_id}/fetch-now")
        assert r.status_code == 200
        tl = r.json()

        # 检查 updates: 至少 1 ai_summary + 1 ai_suggestion
        update_types = {u["update_type"] for u in tl["updates"]}
        assert "ai_summary" in update_types
        assert "ai_suggestion" in update_types
        # latest_ai_suggestion 应该有值
        assert tl["latest_ai_suggestion"] is not None
        assert tl["latest_ai_confidence"] is not None

        # 检查 fetch_jobs: 3 个都 DONE 状态
        statuses = {j["status"] for j in tl["fetch_jobs"]}
        assert statuses == {"done"}


# ========== 4. add_update (user_note) ==========


@pytest.mark.asyncio
async def test_add_user_note() -> None:
    """POST /updates 加 user_note, 异常保持 open"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        ex_id = await _make_exception(c, sid)

        r = await c.post(f"/api/v2/exceptions/{ex_id}/updates", json={
            "summary": "已电话联系客户, 暂不催",
            "accept_ai_suggestion": False,
        })
        assert r.status_code == 201
        new_updates = r.json()
        assert len(new_updates) >= 1
        assert any(u["update_type"] == "user_note" for u in new_updates)

        # 异常仍 open
        r2 = await c.get(f"/api/v2/exceptions/{ex_id}/timeline")
        assert r2.json()["status"] == "open"


# ========== 5. add_update (accept_ai_suggestion=True) ==========


@pytest.mark.asyncio
async def test_add_user_note_with_accept_closes_exception() -> None:
    """accept_ai_suggestion=True → 异常 resolved + 至少 2 条新 update (note + response)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        ex_id = await _make_exception(c, sid)

        r = await c.post(f"/api/v2/exceptions/{ex_id}/updates", json={
            "summary": "已确认船期, 关闭异常",
            "accept_ai_suggestion": True,
        })
        assert r.status_code == 201

        r2 = await c.get(f"/api/v2/exceptions/{ex_id}/timeline")
        tl = r2.json()
        assert tl["status"] == "resolved"
        assert tl["resolved_at"] is not None
        update_types = {u["update_type"] for u in tl["updates"]}
        # user_note + user_response + status_change
        assert "user_note" in update_types
        assert "user_response" in update_types
        assert "status_change" in update_types

        # PENDING fetch job 全部 CANCELLED
        async with AsyncSessionLocal() as db:
            jobs = (await db.execute(
                select(ExceptionFetchJob).where(ExceptionFetchJob.exception_id == ex_id)
            )).scalars().all()
            assert all(j.status == ExceptionFetchJobStatus.CANCELLED for j in jobs)


# ========== 6. ai-question 问答 ==========


@pytest.mark.asyncio
async def test_ai_question_basic() -> None:
    """POST /ai-question 返回 mock answer"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v2/exceptions/ai-question", json={
            "question": "现在有多少个未关闭的异常?",
        })
        assert r.status_code == 200
        ans = r.json()
        assert "answer" in ans
        assert "confidence" in ans
        assert ans["model"] == "mock-gpt-4o-mini"
        # 含 context 关键字
        assert "异常" in ans["answer"] or "count" in ans["answer"].lower() or "未关闭" in ans["answer"]


# ========== 7. fetch jobs 列表 + 状态过滤 ==========


@pytest.mark.asyncio
async def test_list_fetch_jobs_with_status_filter() -> None:
    """GET /fetch-jobs 支持 status 过滤"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        ex_id = await _make_exception(c, sid)

        # 先 PENDING 3 个
        r1 = await c.get(f"/api/v2/exceptions/{ex_id}/fetch-jobs?status=pending")
        assert r1.status_code == 200
        assert len(r1.json()) == 3

        # DONE = 0
        r2 = await c.get(f"/api/v2/exceptions/{ex_id}/fetch-jobs?status=done")
        assert len(r2.json()) == 0

        # 跑一次 fetch-now
        await c.post(f"/api/v2/exceptions/{ex_id}/fetch-now")
        # 再查 DONE = 3
        r3 = await c.get(f"/api/v2/exceptions/{ex_id}/fetch-jobs?status=done")
        assert len(r3.json()) == 3


# ========== 8. accept-suggestion 快捷 endpoint ==========


@pytest.mark.asyncio
async def test_accept_suggestion_endpoint() -> None:
    """POST /accept-suggestion 一键 close"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        ex_id = await _make_exception(c, sid)

        r = await c.post(
            f"/api/v2/exceptions/{ex_id}/accept-suggestion?summary=采纳测试",
        )
        assert r.status_code == 200
        assert r.json()["status"] == "resolved"

        # 再调一次应 400 (已 resolved)
        r2 = await c.post(f"/api/v2/exceptions/{ex_id}/accept-suggestion")
        assert r2.status_code == 400


# ========== 9. 已 resolved 异常的 fetch-now 跳过 ==========


@pytest.mark.asyncio
async def test_fetch_now_skips_resolved() -> None:
    """已 resolved 异常调 fetch-now 不产生新 update"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        ex_id = await _make_exception(c, sid)
        # 直接 close
        await c.post(
            f"/api/v2/exceptions/{ex_id}/accept-suggestion?summary=测试",
        )
        # 调 fetch-now
        r = await c.post(f"/api/v2/exceptions/{ex_id}/fetch-now")
        assert r.status_code == 200
        # updates 只有 4 条 (note + response + status_change + 初始 status_change)
        # 没有 ai_summary / ai_suggestion
        update_types = {u["update_type"] for u in r.json()["updates"]}
        assert "ai_summary" not in update_types
        assert "ai_suggestion" not in update_types


# ========== 10. 404 + 400 异常处理 ==========


@pytest.mark.asyncio
async def test_timeline_404_for_missing_exception() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/exceptions/nonexistent-id/timeline")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_invalid_status_filter_400() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid = await _make_shipment(c)
        ex_id = await _make_exception(c, sid)
        r = await c.get(f"/api/v2/exceptions/{ex_id}/fetch-jobs?status=invalid")
        assert r.status_code == 400
