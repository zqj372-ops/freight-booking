"""Organization API - v0.5

v0.5 单租户, 只暴露 list (过滤) + get by id/slug, 不允许从 UI 创建新组织.
Pydantic 校验确保不会误创建.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor
from app.core.organization_context import get_default_organization
from app.models.organization import Organization
from app.schemas.organization import OrganizationRead, OrganizationUpdate
from app.models._base import AuditAction, AuditActorType
from app.core.audit import write_audit_log

router = APIRouter()


@router.get("/", response_model=list[OrganizationRead])
async def list_organizations(db: AsyncSession = Depends(db_session)) -> list[OrganizationRead]:
    """列出所有 organization. v0.5 应只返回 1 条."""
    stmt = select(Organization).order_by(Organization.created_at.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return [OrganizationRead.model_validate(r) for r in rows]


@router.get("/default", response_model=OrganizationRead)
async def get_default(db: AsyncSession = Depends(db_session)) -> OrganizationRead:
    """拿当前默认组织 (v0.5 单租户, 内部所有写入都用这个)"""
    org = await get_default_organization(db)
    return OrganizationRead.model_validate(org)


@router.get("/{org_id}", response_model=OrganizationRead)
async def get_organization(
    org_id: str, db: AsyncSession = Depends(db_session)
) -> OrganizationRead:
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="organization not found")
    return OrganizationRead.model_validate(org)


@router.patch("/{org_id}", response_model=OrganizationRead)
async def update_organization(
    org_id: str,
    payload: OrganizationUpdate,
    db: AsyncSession = Depends(db_session),
) -> OrganizationRead:
    """修改 organization 配置 (job_no 规则). v0.5 拍板: 只允许改这些, 不允许改 slug/id."""
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="organization not found")

    before = {k: getattr(org, k) for k in payload.model_fields_set}
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(org, k, v)
    await db.commit()
    await db.refresh(org)

    # 写 audit
    after = {k: getattr(org, k) for k in payload.model_fields_set}
    field_changes = {k: {"old": before.get(k), "new": after.get(k)} for k in payload.model_fields_set}
    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="organization",
        entity_id=org.id,
        action=AuditAction.UPDATE,
        actor=Actor(actor_type=AuditActorType.API, actor_user_name="anonymous", actor_job_name="api_call"),
        field_changes=field_changes,
    )
    await db.commit()
    return OrganizationRead.model_validate(org)
