"""v0.6.3 头程时效 API

4 个 endpoint:
- POST  /shipments/{id}/eta                  更新 ETA (操作员/系统)
- GET   /shipments/{id}/eta/history          ETA 变更历史
- GET   /transit/board                       头程看板 (in_transit / delayed / upcoming)
- POST  /transit/check-eta-delays            手动触发 ETA 延误检测 (scheduler bypass)
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction
from app.models.shipment import Shipment
from app.models.transit_time import EtaUpdate, EtaUpdateReason, EtaUpdateSource
from app.schemas.transit_time import (
    EtaUpdateRead,
    EtaUpdateRequest,
)
from app.services import transit_time as transit_service

router = APIRouter()


# ========== 1. POST /shipments/{id}/eta (更新) ==========


@router.post(
    "/shipments/{shipment_id}/eta",
    response_model=EtaUpdateRead,
    status_code=201,
)
async def update_eta(
    shipment_id: str,
    payload: EtaUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> EtaUpdateRead:
    """更新 shipment ETA, 记历史, 必要时建延误异常"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    s = (
        await db.execute(
            select(Shipment).where(
                Shipment.id == shipment_id,
                Shipment.organization_id == org.id,
            )
        )
    ).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")

    eta_upd = await transit_service.update_eta(
        db,
        s,
        new_eta=payload.new_eta,
        reason=EtaUpdateReason(payload.reason),
        change_reason=payload.change_reason,
        source=EtaUpdateSource(payload.source),
        user_id=actor.user_id if hasattr(actor, "user_id") else None,
        user_name=actor.name if hasattr(actor, "name") else None,
        related_document_id=payload.related_document_id,
    )
    await db.commit()
    await db.refresh(eta_upd)

    # audit
    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="shipment_eta",
        entity_id=eta_upd.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes={
            "old_eta": eta_upd.old_eta.isoformat() if eta_upd.old_eta else None,
            "new_eta": eta_upd.new_eta.isoformat(),
            "delta_days": eta_upd.delta_days,
            "reason": eta_upd.reason.value,
            "triggered_exception_id": eta_upd.triggered_exception_id,
        },
    )
    await db.commit()

    return EtaUpdateRead.model_validate(eta_upd)


# ========== 2. GET /shipments/{id}/eta/history ==========


@router.get(
    "/shipments/{shipment_id}/eta/history",
    response_model=list[EtaUpdateRead],
)
async def list_eta_history(
    shipment_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(db_session),
) -> list[EtaUpdateRead]:
    """shipment ETA 变更历史 (按时间倒序)"""
    org = await get_default_organization(db)
    s = (
        await db.execute(
            select(Shipment).where(
                Shipment.id == shipment_id,
                Shipment.organization_id == org.id,
            )
        )
    ).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")

    updates = await transit_service.list_eta_updates(db, shipment_id, limit=limit)
    return [EtaUpdateRead.model_validate(u) for u in updates]


# ========== 3. GET /transit/board ==========


@router.get("/transit/board")
async def get_transit_board(
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """头程看板: in_transit / delayed / upcoming 分类数据"""
    await get_default_organization(db)  # 校验 org
    return await transit_service.build_transit_board(db)


# ========== 4. POST /transit/check-eta-delays (手动触发检测) ==========


@router.post("/transit/check-eta-delays")
async def check_eta_delays_now(
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """手动触发 ETA 延误检测 (绕过 scheduler)"""
    await get_default_organization(db)
    new_exs = await transit_service.detect_eta_delays(db)
    await db.commit()
    return {
        "checked": True,
        "new_exceptions_count": len(new_exs),
        "new_exception_ids": [ex.id for ex in new_exs],
    }
