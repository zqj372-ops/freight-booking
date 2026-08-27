"""v0.6 异常 AI 跟进 - 主 service

整合 fetch + LLM + 写 ExceptionUpdate:
- followup_one_exception: 对一个异常跑一次完整跟进 (fetch → LLM 摘要 → LLM 建议 → 写 update)
- schedule_pending_jobs: 调度入口 (scheduler 每 2h 调一次)
- enqueue_fetch_jobs: 异常创建时建 PENDING job
- answer_ai_question: 全局 AI 问答 (独立入口)

v0.6.1 决策: AI 建议 + 人确认 (不自动 close)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exception_update import (
    ExceptionFetchJob,
    ExceptionFetchJobStatus,
    ExceptionUpdate,
    ExceptionUpdateSource,
    ExceptionUpdateType,
)
from app.models.operational_exception import (
    ExceptionCode,
    ExceptionStatus,
    OperationalException,
)
from app.models.shipment import Shipment
from app.services import exception_fetch
from app.services.llm_service import (
    LlmSummary,
    answer_question,
    suggest_action,
    summarize_fetch_results,
)


# ========== 业务侧调用入口 ==========


async def enqueue_fetch_jobs(
    db: AsyncSession,
    exception: OperationalException,
) -> list[ExceptionFetchJob]:
    """异常创建时建 PENDING 抓取 job (3 个源各一个)

    v0.6.1: 立即可被 scheduler 拉到 (next_run_at = now)
    """
    now = datetime.now(timezone.utc)
    jobs: list[ExceptionFetchJob] = []
    for source in [
        ExceptionUpdateSource.CARRIER_WEBSITE,
        ExceptionUpdateSource.EMAIL,
        ExceptionUpdateSource.WECHAT,
    ]:
        job = ExceptionFetchJob(
            id=str(uuid.uuid4()),
            organization_id=exception.organization_id,
            exception_id=exception.id,
            source=source,
            status=ExceptionFetchJobStatus.PENDING,
            next_run_at=now,  # 立即可被拉到
        )
        db.add(job)
        jobs.append(job)
    await db.flush()
    logger.info(
        f"异常 {exception.id[:8]} enqueue {len(jobs)} 个抓取 job"
    )
    return jobs


async def on_exception_created(
    db: AsyncSession,
    exception: OperationalException,
) -> None:
    """异常创建后钩子: 自动 enqueue 抓取 job + 写初始 update

    任何地方 (API / workflow service / forecast service) 创建异常后,
    调一下这个函数, AI 跟进就自动开始了。
    """
    await enqueue_fetch_jobs(db, exception)
    # 写个 STATUS_CHANGE 标识 AI 跟进已启动
    init_update = ExceptionUpdate(
        id=str(uuid.uuid4()),
        organization_id=exception.organization_id,
        exception_id=exception.id,
        update_type=ExceptionUpdateType.STATUS_CHANGE,
        source=ExceptionUpdateSource.AI_INFERENCE,
        summary="异常创建, AI 跟进已启动 (3 个抓取源, 最多 84 次 / 7 天)",
        created_by_type="system",
    )
    db.add(init_update)
    await db.flush()


async def mark_fetch_jobs_done_for_sources(
    db: AsyncSession,
    exception_id: str,
    sources: list[ExceptionUpdateSource],
) -> int:
    """fetch_now 跑完后, 把对应 PENDING fetch_job 标 DONE + 推进 next_run_at

    否则 scheduler 会再次跑同样的源, 制造重复 update。
    """
    now = datetime.now(timezone.utc)
    pending_jobs = (
        await db.execute(
            select(ExceptionFetchJob).where(
                and_(
                    ExceptionFetchJob.exception_id == exception_id,
                    ExceptionFetchJob.status == ExceptionFetchJobStatus.PENDING,
                    ExceptionFetchJob.source.in_(sources),
                )
            )
        )
    ).scalars().all()
    for j in pending_jobs:
        j.status = ExceptionFetchJobStatus.DONE
        j.last_run_at = now
        j.run_count += 1
        if j.run_count >= j.max_runs:
            j.status = ExceptionFetchJobStatus.CANCELLED
            j.last_error = f"达到 max_runs={j.max_runs}, 自动 CANCELLED"
        else:
            j.next_run_at = now + timedelta(hours=2)
    await db.flush()
    return len(pending_jobs)


async def followup_one_exception(
    db: AsyncSession,
    exception: OperationalException,
    sources: list[ExceptionUpdateSource] | None = None,
) -> list[ExceptionUpdate]:
    """对一个异常跑一次完整跟进

    流程:
    1. 查 shipment
    2. fetch_all_sources
    3. LLM 摘要 (写 ExceptionUpdate.ai_summary)
    4. LLM 建议 (写 ExceptionUpdate.ai_suggestion)
    5. 如果异常已 resolved/auto_closed, 不跑 (避免浪费)

    Returns:
        新建的 ExceptionUpdate 列表
    """
    if exception.status != ExceptionStatus.OPEN:
        logger.debug(f"异常 {exception.id[:8]} 非 open ({exception.status.value}), 跳过跟进")
        return []

    # 1. 查 shipment
    shipment = (
        await db.execute(
            select(Shipment).where(Shipment.id == exception.shipment_id)
        )
    ).scalar_one_or_none()
    if not shipment:
        logger.warning(f"异常 {exception.id[:8]} 找不到 shipment, 跳过")
        return []

    # 2. fetch
    results = await exception_fetch.fetch_all_sources(db, shipment, exception, sources)
    if not results:
        return []

    # 3. LLM 摘要
    fetch_dicts = [
        {"source": r.source.value, "summary": r.summary, "progress_made": r.progress_made}
        for r in results
    ]
    summary_llm = summarize_fetch_results(fetch_dicts, exception.code.value)
    has_recent_progress = any(r.progress_made for r in results)

    # 4. LLM 建议
    suggestion_llm = suggest_action(exception.code.value, fetch_dicts, has_recent_progress)

    # 5. 写 ExceptionUpdate
    new_updates: list[ExceptionUpdate] = []

    # 5a. 写每次 fetch 的原始结果 (如果有进展)
    for r in results:
        if not r.progress_made:
            continue
        upd = ExceptionUpdate(
            id=str(uuid.uuid4()),
            organization_id=exception.organization_id,
            exception_id=exception.id,
            update_type=ExceptionUpdateType.AI_FETCH,
            source=r.source,
            summary=r.summary,
            raw_data=r.raw_data,
            ai_model=summary_llm.model,
            created_by_type="ai",
        )
        db.add(upd)
        new_updates.append(upd)

    # 5b. 写 LLM 摘要 (只写一次, 包含所有 fetch 的总评)
    summary_update = ExceptionUpdate(
        id=str(uuid.uuid4()),
        organization_id=exception.organization_id,
        exception_id=exception.id,
        update_type=ExceptionUpdateType.AI_SUMMARY,
        source=ExceptionUpdateSource.AI_INFERENCE,
        summary=summary_llm.text,
        raw_data=summary_llm.raw,
        ai_model=summary_llm.model,
        ai_confidence=summary_llm.confidence,
        created_by_type="ai",
    )
    db.add(summary_update)
    new_updates.append(summary_update)

    # 5c. 写 AI 建议 (让操作员决定采纳/拒绝)
    suggestion_update = ExceptionUpdate(
        id=str(uuid.uuid4()),
        organization_id=exception.organization_id,
        exception_id=exception.id,
        update_type=ExceptionUpdateType.AI_SUGGESTION,
        source=ExceptionUpdateSource.AI_INFERENCE,
        summary=suggestion_llm.text,
        raw_data=suggestion_llm.raw,
        ai_model=suggestion_llm.model,
        ai_confidence=suggestion_llm.confidence,
        created_by_type="ai",
    )
    db.add(suggestion_update)
    new_updates.append(suggestion_update)

    await db.flush()
    logger.info(
        f"异常 {exception.id[:8]} 跟进完成, 新增 {len(new_updates)} 条 update "
        f"(fetch={sum(1 for u in new_updates if u.update_type == ExceptionUpdateType.AI_FETCH)}, "
        f"summary/suggestion 各 1)"
    )
    return new_updates


async def followup_one_job(
    db: AsyncSession,
    job: ExceptionFetchJob,
) -> int:
    """对单个 fetch job 执行一次

    Returns:
        新建 ExceptionUpdate 数
    """
    job.status = ExceptionFetchJobStatus.RUNNING
    job.last_run_at = datetime.now(timezone.utc)
    job.run_count += 1
    try:
        # 查 exception
        exception = (
            await db.execute(
                select(OperationalException).where(
                    OperationalException.id == job.exception_id
                )
            )
        ).scalar_one_or_none()
        if not exception:
            job.status = ExceptionFetchJobStatus.FAILED
            job.last_error = "exception not found"
            return 0

        # 跑跟进 (单源)
        new_updates = await followup_one_exception(db, exception, sources=[job.source])
        job.status = ExceptionFetchJobStatus.DONE
        job.last_error = None
        return len(new_updates)
    except Exception as e:
        logger.exception(f"fetch job {job.id} failed: {e}")
        job.status = ExceptionFetchJobStatus.FAILED
        job.last_error = str(e)[:500]
        return 0
    finally:
        # 决定下次跑时间 / 是否放弃
        if job.status in (
            ExceptionFetchJobStatus.DONE,
            ExceptionFetchJobStatus.FAILED,
        ):
            if job.run_count >= job.max_runs:
                job.status = ExceptionFetchJobStatus.CANCELLED
                job.last_error = f"达到 max_runs={job.max_runs}, 自动 CANCELLED"
            else:
                # 下次 2h 后
                job.next_run_at = datetime.now(timezone.utc) + timedelta(hours=2)


# ========== 调度入口 (scheduler 每 2h 调一次) ==========


async def schedule_pending_jobs(db: AsyncSession, max_jobs: int = 50) -> int:
    """拉所有 PENDING 且 next_run_at <= now 的 job, 跑完一个 commit 一次

    Returns:
        处理的 job 数
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(ExceptionFetchJob)
        .where(
            and_(
                ExceptionFetchJob.status == ExceptionFetchJobStatus.PENDING,
                ExceptionFetchJob.next_run_at <= now,
            )
        )
        .order_by(ExceptionFetchJob.next_run_at.asc())
        .limit(max_jobs)
    )
    jobs = (await db.execute(stmt)).scalars().all()
    if not jobs:
        return 0

    processed = 0
    for job in jobs:
        try:
            await followup_one_job(db, job)
            await db.commit()
            processed += 1
        except Exception as e:
            logger.exception(f"schedule job {job.id} commit failed: {e}")
            await db.rollback()
    return processed


# ========== 用户操作: 加备注 / 采纳 AI 建议 ==========


async def add_user_note(
    db: AsyncSession,
    exception: OperationalException,
    summary: str,
    user_id: str | None = None,
    user_name: str | None = None,
    accept_ai_suggestion: bool = False,
) -> ExceptionUpdate:
    """用户手动加 update (备注/采纳/拒绝 AI 建议)

    accept_ai_suggestion=True 时, 同时:
    1. 写 user_response update
    2. 把异常 status → resolved (用户确认采纳 AI 建议)
    3. 取消所有 PENDING fetch job
    """
    upd = ExceptionUpdate(
        id=str(uuid.uuid4()),
        organization_id=exception.organization_id,
        exception_id=exception.id,
        update_type=ExceptionUpdateType.USER_NOTE,
        source=ExceptionUpdateSource.USER,
        summary=summary,
        created_by_type="user",
        created_by_user_id=user_id,
        created_by_user_name=user_name,
    )
    db.add(upd)

    if accept_ai_suggestion:
        # 1. 写 user_response update
        resp_upd = ExceptionUpdate(
            id=str(uuid.uuid4()),
            organization_id=exception.organization_id,
            exception_id=exception.id,
            update_type=ExceptionUpdateType.USER_RESPONSE,
            source=ExceptionUpdateSource.USER,
            summary=f"采纳 AI 建议: {summary[:100]}",
            created_by_type="user",
            created_by_user_id=user_id,
            created_by_user_name=user_name,
        )
        db.add(resp_upd)

        # 2. close 异常
        exception.status = ExceptionStatus.RESOLVED
        exception.resolved_at = datetime.now(timezone.utc)
        exception.resolution = summary[:200]

        # 3. 写 status_change update
        status_upd = ExceptionUpdate(
            id=str(uuid.uuid4()),
            organization_id=exception.organization_id,
            exception_id=exception.id,
            update_type=ExceptionUpdateType.STATUS_CHANGE,
            source=ExceptionUpdateSource.USER,
            summary=f"异常状态变更: open → resolved (采纳 AI 建议)",
            created_by_type="user",
            created_by_user_id=user_id,
            created_by_user_name=user_name,
        )
        db.add(status_upd)

        # 4. 取消所有 PENDING fetch job
        pending_jobs = (
            await db.execute(
                select(ExceptionFetchJob).where(
                    and_(
                        ExceptionFetchJob.exception_id == exception.id,
                        ExceptionFetchJob.status == ExceptionFetchJobStatus.PENDING,
                    )
                )
            )
        ).scalars().all()
        for j in pending_jobs:
            j.status = ExceptionFetchJobStatus.CANCELLED
            j.last_error = "异常已 resolved, 自动取消"

    await db.flush()
    return upd


# ========== 全局 AI 问答 ==========


async def answer_ai_question(
    db: AsyncSession,
    question: str,
    shipment_id: str | None = None,
    exception_id: str | None = None,
) -> LlmSummary:
    """全局 AI 问答 (什么都能问)

    v0.6.1 mock: 关键词匹配 + 业务 context
    业务 context 收集:
    - shipment_count: 总业务单数
    - exception_count: OPEN 异常数 (按 severity 分)
    - forecast: 本周预报数 + 配载率 (v0.6)

    限定范围:
    - shipment_id: 只看该 shipment
    - exception_id: 只看该 exception
    """
    ctx: dict[str, Any] = {}

    if exception_id:
        ex = (
            await db.execute(
                select(OperationalException).where(
                    OperationalException.id == exception_id
                )
            )
        ).scalar_one_or_none()
        if ex:
            ctx["exception_code"] = ex.code.value
            ctx["exception_severity"] = ex.severity.value

    if shipment_id:
        s = (
            await db.execute(select(Shipment).where(Shipment.id == shipment_id))
        ).scalar_one_or_none()
        if s:
            ctx["shipment_id"] = s.id
            ctx["shipment_stage"] = s.stage.value
            ctx["pol"] = s.pol
            ctx["pod"] = s.pod

    # 业务 context 收集 (简化版, 全部业务用)
    shipment_total = (
        await db.execute(select(Shipment.id).limit(1000))
    ).all()
    ctx["count"] = len(shipment_total)

    # 异常统计: 始终初始化 3 个 severity = 0, 没数据也不 KeyError
    ctx.setdefault("info", 0)
    ctx.setdefault("warning", 0)
    ctx.setdefault("critical", 0)

    from sqlalchemy import func as sa_func

    ex_total = (
        await db.execute(
            select(OperationalException.severity, sa_func.count())
            .where(OperationalException.status == ExceptionStatus.OPEN)
            .group_by(OperationalException.severity)
        )
    ).all()
    total_open = 0
    for sev, n in ex_total:
        ctx[sev.value] = n
        total_open += n
    ctx["exception_count"] = total_open
    ctx["open"] = total_open

    return answer_question(question, ctx)
