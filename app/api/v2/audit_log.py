"""AuditLog API - v0.5 审计查询"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.organization_context import get_default_organization
from app.models.audit import AuditLog
from app.schemas.audit_log import AuditLogRead

router = APIRouter()


@router.get("/", response_model=list[AuditLogRead])
async def list_audit_logs(
    entity_type: str | None = Query(None, description="shipment / booking_request / ..."),
    entity_id: str | None = Query(None),
    action: str | None = Query(None),
    actor_user_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[AuditLogRead]:
    """按 entity / actor 过滤查审计日志. v0.5 不做全文检索."""
    org = await get_default_organization(db)
    stmt = select(AuditLog).where(AuditLog.organization_id == org.id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [AuditLogRead.model_validate(r) for r in rows]


@router.get("/by-entity/{entity_type}/{entity_id}", response_model=list[AuditLogRead])
async def get_entity_history(
    entity_type: str,
    entity_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(db_session),
) -> list[AuditLogRead]:
    """拿一个实体的完整审计历史 (业务详情页 "操作记录" tab 用)"""
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
        .order_by(AuditLog.created_at.asc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [AuditLogRead.model_validate(r) for r in rows]
