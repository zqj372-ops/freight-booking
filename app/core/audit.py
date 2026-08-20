"""v0.5 actor context + AuditLog 写入辅助

- actor: 从 FastAPI request 取 X-User-Id / X-User-Name header
- 没传 → 默认 actor_type=API, user_id=NULL, name='anonymous', job_name='api_call'
- 调度任务 / 内部 service 调用: 显式传 actor 参数
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import AuditAction, AuditActorType
from app.models.audit import AuditLog


@dataclass(frozen=True)
class Actor:
    """调用方身份 (v0.5 简化版, 不接 JWT)"""

    actor_type: AuditActorType
    actor_user_id: str | None = None
    actor_user_name: str | None = None
    actor_job_name: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> "Actor":
        """从 request headers 提取"""
        user_id = request.headers.get("X-User-Id") or None
        user_name = request.headers.get("X-User-Name") or None
        if user_id:
            return cls(
                actor_type=AuditActorType.USER,
                actor_user_id=user_id,
                actor_user_name=user_name,
            )
        return cls(
            actor_type=AuditActorType.API,
            actor_user_id=None,
            actor_user_name="anonymous",
            actor_job_name="api_call",
        )

    @classmethod
    def system(cls, job_name: str = "system") -> "Actor":
        return cls(actor_type=AuditActorType.SYSTEM, actor_job_name=job_name)

    @classmethod
    def scheduled(cls, job_name: str) -> "Actor":
        return cls(actor_type=AuditActorType.SCHEDULED_JOB, actor_job_name=job_name)


async def write_audit_log(
    db: AsyncSession,
    *,
    organization_id: str,
    entity_type: str,
    entity_id: str,
    action: AuditAction,
    actor: Actor,
    field_changes: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditLog:
    """写一条 audit log, commit 由调用方负责

    v0.5 不做中间件, 由 service 层显式调用. 原因: 中间件做 diff 自动捕获成本高,
    业务字段含义复杂 (例如 stage 推导 vs 手动改), service 层显式控制更清晰.
    """
    log = AuditLog(
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_type=actor.actor_type,
        actor_user_id=actor.actor_user_id,
        actor_user_name=actor.actor_user_name,
        actor_job_name=actor.actor_job_name,
        field_changes=field_changes,
        context=context,
        reason=reason,
    )
    db.add(log)
    await db.flush()
    return log
