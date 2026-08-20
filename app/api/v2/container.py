"""Container API - v0.5 柜管理"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction
from app.models.container import Container, ContainerStatus
from app.models.shipment import Shipment
from app.schemas.container import ContainerCreate, ContainerRead, ContainerUpdate

router = APIRouter()


@router.post("/", response_model=ContainerRead, status_code=201)
async def create_container(
    payload: ContainerCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ContainerRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    s = (await db.execute(
        select(Shipment).where(Shipment.id == payload.shipment_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")

    c = Container(
        organization_id=org.id,
        shipment_id=payload.shipment_id,
        container_type=payload.container_type,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="container",
        entity_id=c.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={"after": payload.model_dump(mode="json")},
    )
    await db.commit()
    return ContainerRead.model_validate(c)


@router.get("/{container_id}", response_model=ContainerRead)
async def get_container(
    container_id: str, db: AsyncSession = Depends(db_session)
) -> ContainerRead:
    c = (await db.execute(
        select(Container).where(Container.id == container_id)
    )).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="container not found")
    return ContainerRead.model_validate(c)


@router.patch("/{container_id}", response_model=ContainerRead)
async def update_container(
    container_id: str,
    payload: ContainerUpdate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ContainerRead:
    c = (await db.execute(
        select(Container).where(Container.id == container_id)
    )).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="container not found")
    actor = Actor.from_request(request)

    before = {k: getattr(c, k) for k in payload.model_fields_set}

    # 自动推 status
    new_status: ContainerStatus | None = None
    if "loaded_time" in payload.model_fields_set and payload.loaded_time:
        new_status = ContainerStatus.LOADED
    elif "pickup_time" in payload.model_fields_set and payload.pickup_time:
        new_status = ContainerStatus.PICKED_UP
    elif "return_time" in payload.model_fields_set and payload.return_time:
        new_status = ContainerStatus.RETURNED

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    if new_status is not None:
        c.status = new_status
    await db.commit()
    await db.refresh(c)

    # JSON 安全的 field_changes (datetime 转 isoformat)
    def _safe(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    after = {k: getattr(c, k) for k in payload.model_fields_set}
    field_changes = {k: {"old": _safe(before.get(k)), "new": _safe(after.get(k))} for k in payload.model_fields_set}
    if new_status is not None:
        field_changes["status"] = {"old": "previous", "new": new_status.value}
    await write_audit_log(
        db,
        organization_id=c.organization_id,
        entity_type="container",
        entity_id=c.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes=field_changes,
    )
    await db.commit()
    return ContainerRead.model_validate(c)
