"""v0.6 异常 AI 跟进 API

6 个核心 endpoint (全部在 /api/v2/exceptions 下):
- GET    /{id}/timeline           异常 timeline (含 updates + fetch_jobs + AI 建议)
- POST   /{id}/updates            用户加备注 / 采纳 AI 建议
- POST   /{id}/fetch-now          立即触发 AI 跟进 (跳过调度)
- GET    /{id}/fetch-jobs         抓取 job 列表
- POST   /ai-question             全局 AI 问答 (任何问题)
- POST   /{id}/accept-suggestion  采纳 AI 建议 (close 异常)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction
from app.models.exception_update import (
    ExceptionFetchJob,
    ExceptionFetchJobStatus,
    ExceptionUpdate,
    ExceptionUpdateSource,
    ExceptionUpdateType,
)
from app.models.operational_exception import (
    ExceptionStatus,
    OperationalException,
)
from app.models.shipment import Shipment
from app.schemas.exception_update import (
    ExceptionAiAnswer,
    ExceptionAiQuestionRequest,
    ExceptionFetchJobRead,
    ExceptionFetchNowRequest,
    ExceptionTimeline,
    ExceptionUpdateCreate,
    ExceptionUpdateRead,
)
from app.services import exception_followup
from app.services.exception_followup import (
    add_user_note,
    answer_ai_question,
    followup_one_exception,
)

router = APIRouter()


# ========== 工具函数 ==========


async def _get_exception_or_404(
    db: AsyncSession, exception_id: str, org_id: str
) -> OperationalException:
    ex = (
        await db.execute(
            select(OperationalException).where(
                and_(
                    OperationalException.id == exception_id,
                    OperationalException.organization_id == org_id,
                )
            )
        )
    ).scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="exception not found")
    return ex


async def _get_shipment(
    db: AsyncSession, shipment_id: str
) -> Shipment | None:
    return (
        await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    ).scalar_one_or_none()


# ========== 1. GET /{id}/timeline ==========


@router.get("/{exception_id}/timeline", response_model=ExceptionTimeline)
async def get_exception_timeline(
    exception_id: str,
    db: AsyncSession = Depends(db_session),
) -> ExceptionTimeline:
    """异常 timeline 整体响应 (前端异常详情页用)"""
    org = await get_default_organization(db)
    ex = await _get_exception_or_404(db, exception_id, org.id)

    # updates 按时间倒序
    updates = (
        await db.execute(
            select(ExceptionUpdate)
            .where(ExceptionUpdate.exception_id == exception_id)
            .order_by(ExceptionUpdate.created_at.desc())
        )
    ).scalars().all()

    # fetch jobs
    fetch_jobs = (
        await db.execute(
            select(ExceptionFetchJob)
            .where(ExceptionFetchJob.exception_id == exception_id)
            .order_by(ExceptionFetchJob.created_at.desc())
        )
    ).scalars().all()

    # latest_ai_suggestion (取最新的 ai_suggestion 类型)
    latest_sugg = None
    latest_conf = None
    for u in updates:
        if u.update_type == ExceptionUpdateType.AI_SUGGESTION:
            latest_sugg = u.summary
            latest_conf = u.ai_confidence
            break

    return ExceptionTimeline(
        exception_id=ex.id,
        shipment_id=ex.shipment_id,
        code=ex.code.value,
        severity=ex.severity.value,
        status=ex.status.value,
        detected_at=ex.detected_at,
        resolved_at=ex.resolved_at,
        resolution=ex.resolution,
        updates=[ExceptionUpdateRead.model_validate(u) for u in updates],
        fetch_jobs=[ExceptionFetchJobRead.model_validate(j) for j in fetch_jobs],
        latest_ai_suggestion=latest_sugg,
        latest_ai_confidence=latest_conf,
    )


# ========== 2. POST /{id}/updates ==========


@router.post(
    "/{exception_id}/updates",
    response_model=list[ExceptionUpdateRead],
    status_code=201,
)
async def add_update(
    exception_id: str,
    payload: ExceptionUpdateCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> list[ExceptionUpdateRead]:
    """用户手动加 update (备注/采纳 AI 建议)"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    ex = await _get_exception_or_404(db, exception_id, org.id)

    # 1. 写 user_note
    note = await add_user_note(
        db,
        ex,
        summary=payload.summary,
        user_id=actor.user_id if hasattr(actor, "user_id") else None,
        user_name=actor.name if hasattr(actor, "name") else None,
        accept_ai_suggestion=payload.accept_ai_suggestion,
    )
    await db.commit()
    await db.refresh(note)

    # 2. 重新查所有 update (因为 accept 时写了多条)
    updates = (
        await db.execute(
            select(ExceptionUpdate)
            .where(ExceptionUpdate.exception_id == exception_id)
            .order_by(ExceptionUpdate.created_at.desc())
        )
    ).scalars().all()
    # 只返本次新增的 (created_at > note.created_at - 1s)
    now_aware = datetime.now(timezone.utc)
    new_updates = []
    for u in updates:
        ts = u.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (now_aware - ts).total_seconds() < 10:
            new_updates.append(u)
    if not new_updates:
        new_updates = [note]

    # 3. audit
    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="exception_update",
        entity_id=note.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes={
            "summary": payload.summary,
            "accept_ai_suggestion": payload.accept_ai_suggestion,
        },
    )
    await db.commit()

    return [ExceptionUpdateRead.model_validate(u) for u in new_updates]


# ========== 3. POST /{id}/fetch-now ==========


@router.post("/{exception_id}/fetch-now", response_model=ExceptionTimeline)
async def fetch_now(
    exception_id: str,
    payload: ExceptionFetchNowRequest | None = None,
    db: AsyncSession = Depends(db_session),
) -> ExceptionTimeline:
    """立即触发 AI 跟进 (跳过调度), 跑完返新 timeline"""
    org = await get_default_organization(db)
    ex = await _get_exception_or_404(db, exception_id, org.id)

    sources = None
    if payload and payload.sources:
        sources = [ExceptionUpdateSource(s) for s in payload.sources]

    await followup_one_exception(db, ex, sources=sources)
    # 同步 fetch_job 状态 (避免 scheduler 重复跑)
    if sources:
        from app.services.exception_followup import mark_fetch_jobs_done_for_sources
        await mark_fetch_jobs_done_for_sources(db, ex.id, sources)
    else:
        from app.services.exception_followup import mark_fetch_jobs_done_for_sources
        from app.models.exception_update import ExceptionUpdateSource as _ES
        await mark_fetch_jobs_done_for_sources(
            db, ex.id,
            [_ES.CARRIER_WEBSITE, _ES.EMAIL, _ES.WECHAT],
        )
    await db.commit()
    await db.refresh(ex)

    # 返新 timeline (复用上面 endpoint 逻辑)
    return await get_exception_timeline(exception_id, db)


# ========== 4. GET /{id}/fetch-jobs ==========


@router.get(
    "/{exception_id}/fetch-jobs",
    response_model=list[ExceptionFetchJobRead],
)
async def list_fetch_jobs(
    exception_id: str,
    status: str | None = Query(None, description="pending/running/done/failed/cancelled"),
    db: AsyncSession = Depends(db_session),
) -> list[ExceptionFetchJobRead]:
    """异常抓取 job 列表"""
    org = await get_default_organization(db)
    # 确认异常存在 (避免泄漏)
    await _get_exception_or_404(db, exception_id, org.id)

    stmt = select(ExceptionFetchJob).where(
        ExceptionFetchJob.exception_id == exception_id
    )
    if status:
        try:
            s_enum = ExceptionFetchJobStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
        stmt = stmt.where(ExceptionFetchJob.status == s_enum)
    stmt = stmt.order_by(ExceptionFetchJob.created_at.desc())

    jobs = (await db.execute(stmt)).scalars().all()
    return [ExceptionFetchJobRead.model_validate(j) for j in jobs]


# ========== 5. POST /ai-question (全局) ==========


@router.post("/ai-question", response_model=ExceptionAiAnswer)
async def ai_question(
    payload: ExceptionAiQuestionRequest,
    db: AsyncSession = Depends(db_session),
) -> ExceptionAiAnswer:
    """全局 AI 问答 (任何问题, mock 走关键词匹配)"""
    await get_default_organization(db)  # 校验 org 存在

    llm_ans = await answer_ai_question(
        db,
        question=payload.question,
        shipment_id=payload.shipment_id,
        exception_id=payload.exception_id,
    )
    return ExceptionAiAnswer(
        question=payload.question,
        answer=llm_ans.text,
        confidence=llm_ans.confidence,
        sources=llm_ans.sources,
        model=llm_ans.model,
    )


# ========== 6. POST /{id}/accept-suggestion (close 异常) ==========


@router.post(
    "/{exception_id}/accept-suggestion",
    response_model=ExceptionTimeline,
)
async def accept_suggestion(
    exception_id: str,
    summary: str = "采纳 AI 建议, 异常关闭",
    request: Request = None,  # type: ignore
    db: AsyncSession = Depends(db_session),
) -> ExceptionTimeline:
    """快捷: 采纳 AI 最新建议并 close 异常"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request) if request else None
    ex = await _get_exception_or_404(db, exception_id, org.id)

    if ex.status != ExceptionStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail=f"异常已 {ex.status.value}, 不能采纳建议",
        )

    await add_user_note(
        db,
        ex,
        summary=summary,
        user_id=actor.user_id if actor and hasattr(actor, "user_id") else None,
        user_name=actor.name if actor and hasattr(actor, "name") else None,
        accept_ai_suggestion=True,
    )
    await db.commit()
    await db.refresh(ex)

    if actor:
        await write_audit_log(
            db,
            organization_id=org.id,
            entity_type="operational_exception",
            entity_id=ex.id,
            action=AuditAction.UPDATE,
            actor=actor,
            field_changes={"status": ex.status.value, "resolution": summary},
        )
        await db.commit()

    return await get_exception_timeline(exception_id, db)
