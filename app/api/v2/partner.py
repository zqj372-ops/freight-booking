"""Partner API - v0.5 替代 v0.4 /api/v1/agents"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction, PartnerType
from app.models.partner import Partner
from app.schemas.partner import PartnerCreate, PartnerRead, PartnerUpdate

router = APIRouter()


async def _check_duplicate(
    db: AsyncSession, org_id: str, short_code: str | None
) -> None:
    if not short_code:
        return
    stmt = select(Partner).where(
        Partner.organization_id == org_id,
        Partner.short_code == short_code,
    )
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"short_code '{short_code}' already exists")


@router.get("/", response_model=list[PartnerRead])
async def list_partners(
    partner_type: PartnerType | None = Query(None, description="按类型过滤"),
    is_active: bool | None = None,
    search: str | None = Query(None, description="按 name/short_code 模糊"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(db_session),
) -> list[PartnerRead]:
    org = await get_default_organization(db)
    stmt = select(Partner).where(Partner.organization_id == org.id)
    if partner_type is not None:
        stmt = stmt.where(Partner.partner_type == partner_type)
    if is_active is not None:
        stmt = stmt.where(Partner.is_active == is_active)
    if search:
        like = f"%{search}%"
        stmt = stmt.where((Partner.name.like(like)) | (Partner.short_code.like(like)))
    stmt = stmt.order_by(Partner.partner_type.asc(), Partner.name.asc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [PartnerRead.model_validate(r) for r in rows]


@router.post("/", response_model=PartnerRead, status_code=201)
async def create_partner(
    payload: PartnerCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> PartnerRead:
    org = await get_default_organization(db)
    await _check_duplicate(db, org.id, payload.short_code)
    actor = Actor.from_request(request)

    p = Partner(organization_id=org.id, **payload.model_dump())
    db.add(p)
    await db.commit()
    await db.refresh(p)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="partner",
        entity_id=p.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={"after": payload.model_dump(mode="json")},
    )
    await db.commit()
    return PartnerRead.model_validate(p)


@router.get("/{partner_id}", response_model=PartnerRead)
async def get_partner(
    partner_id: str, db: AsyncSession = Depends(db_session)
) -> PartnerRead:
    p = (await db.execute(select(Partner).where(Partner.id == partner_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="partner not found")
    return PartnerRead.model_validate(p)


@router.patch("/{partner_id}", response_model=PartnerRead)
async def update_partner(
    partner_id: str,
    payload: PartnerUpdate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> PartnerRead:
    p = (await db.execute(select(Partner).where(Partner.id == partner_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="partner not found")
    actor = Actor.from_request(request)

    # short_code 唯一性检查 (如果改了)
    if "short_code" in payload.model_fields_set and payload.short_code != p.short_code:
        await _check_duplicate(db, p.organization_id, payload.short_code)

    before = {k: getattr(p, k) for k in payload.model_fields_set}
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)

    after = {k: getattr(p, k) for k in payload.model_fields_set}
    field_changes = {k: {"old": before.get(k), "new": after.get(k)} for k in payload.model_fields_set}
    await write_audit_log(
        db,
        organization_id=p.organization_id,
        entity_type="partner",
        entity_id=p.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes=field_changes,
    )
    await db.commit()
    return PartnerRead.model_validate(p)


@router.delete("/{partner_id}", status_code=204)
async def delete_partner(
    partner_id: str,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> None:
    """软删: is_active=false, 不物理删除"""
    p = (await db.execute(select(Partner).where(Partner.id == partner_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="partner not found")
    actor = Actor.from_request(request)
    p.is_active = False
    await db.commit()

    await write_audit_log(
        db,
        organization_id=p.organization_id,
        entity_type="partner",
        entity_id=p.id,
        action=AuditAction.DELETE,
        actor=actor,
        reason="soft delete via API",
    )
    await db.commit()
