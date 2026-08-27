"""Forecast API - v0.6 预报货量统计

v0.6 阶段 0:
- CRUD (单条 + 批量)
- 多源 dedup 自动处理 (返回 dedup action 让前端展示)
- 周汇总 (按 ISO 周 + 路线 + 客户聚合)
- 配载 (forecast ↔ shipment)
- 取消
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models.forecast import Forecast, ForecastSource, ForecastStatus
from app.models.partner import Partner
from app.schemas.forecast import (
    ForecastAllocateRequest,
    ForecastBulkCreate,
    ForecastBulkCreateResult,
    ForecastCancelRequest,
    ForecastCreate,
    ForecastDedupCheck,
    ForecastRead,
    ForecastUpdate,
    ForecastWeeklySummary,
)
from app.services.forecast import (
    allocate_forecast,
    auto_detect_forecast_exceptions,
    cancel_forecast,
    create_forecast,
    find_duplicate_forecasts,
    iso_week_start,
    make_content_fingerprint,
    weekly_summary,
)

router = APIRouter()


# ========== CRUD ==========


@router.post("/", response_model=ForecastRead, status_code=201)
async def create_forecast_endpoint(
    payload: ForecastCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ForecastRead:
    """建预报 (单条) + dedup 自动处理

    冲突处理:
    - 同源同 source_ref (UNIQUE): 返 409
    - 跨源同 fingerprint: 自动 merge, 升级为 confirmed
    - 同源同 fingerprint 不同 source_ref: needs_human, 返 200 + notes 标"疑似重复"
    """
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    # 验证 customer_id 存在且是 customer
    cp = (await db.execute(
        select(Partner).where(Partner.id == payload.customer_id)
    )).scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=400, detail=f"customer_id {payload.customer_id} not found")

    try:
        f, action = await create_forecast(
            db,
            organization_id=org.id,
            actor_user_id=actor.actor_user_id,
            actor_user_name=actor.actor_user_name,
            payload=payload.model_dump(),
        )
        await db.commit()
        await db.refresh(f)
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"同源同 source_ref 已存在 (source={payload.source}, source_ref={payload.source_ref}). {e}",
        )

    # write audit
    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="forecast",
        entity_id=f.id,
        action="create",
        actor=actor,
        field_changes={
            "after": payload.model_dump(mode="json"),
            "dedup_action": action,
        },
    )
    await db.commit()
    return ForecastRead.model_validate(f)


@router.post("/bulk", response_model=ForecastBulkCreateResult)
async def bulk_create_forecasts(
    payload: ForecastBulkCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ForecastBulkCreateResult:
    """批量建预报 (CSV 导入用)

    dry_run=true: 仅 dedup 检测, 不入库
    dry_run=false: 真实导入, dedup merge 自动 confirm
    """
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    created = 0
    duplicates = 0
    errors: list[dict] = []
    details: list[ForecastDedupCheck] = []

    for fc in payload.forecasts:
        try:
            fingerprint = make_content_fingerprint(
                fc.customer_id, fc.pol, fc.pod, fc.target_etd, fc.container_type
            )
            existing = await find_duplicate_forecasts(
                db, org.id,
                customer_id=fc.customer_id, pol=fc.pol, pod=fc.pod,
                target_etd=fc.target_etd, container_type=fc.container_type,
                source=ForecastSource(fc.source), source_ref=fc.source_ref,
            )
            if not payload.dry_run:
                f, action = await create_forecast(
                    db,
                    organization_id=org.id,
                    actor_user_id=actor.actor_user_id,
                    actor_user_name=actor.actor_user_name,
                    payload=fc.model_dump(),
                )
                details.append(ForecastDedupCheck(
                    fingerprint=fingerprint,
                    match_count=len(existing),
                    match_ids=[e.id for e in existing],
                    new_forecast_id=f.id,
                    action=action,
                    note=f"[{action}] {fc.customer_name} {fc.pol}→{fc.pod} {fc.container_count}×{fc.container_type} etd={fc.target_etd}",
                ))
                if action == "needs_human":
                    duplicates += 1
                else:
                    created += 1
            else:
                # dry_run: 仅返回 dedup 预判
                action, note = (
                    ("create_new", "无重复, 可安全新建") if not existing
                    else ("merge_into_existing", f"已有 {len(existing)} 条同内容")
                )
                details.append(ForecastDedupCheck(
                    fingerprint=fingerprint,
                    match_count=len(existing),
                    match_ids=[e.id for e in existing],
                    new_forecast_id=None,
                    action=action,
                    note=note,
                ))
        except Exception as e:
            errors.append({"input": fc.model_dump(mode="json"), "error": str(e)[:200]})

    if not payload.dry_run:
        await db.commit()
    return ForecastBulkCreateResult(
        created=created,
        duplicates=duplicates,
        errors=errors,
        details=details,
    )


@router.get("/", response_model=list[ForecastRead])
async def list_forecasts(
    status: str | None = Query(None),
    source: str | None = Query(None),
    customer_id: str | None = Query(None),
    pol: str | None = Query(None),
    pod: str | None = Query(None),
    target_etd_from: date | None = Query(None, description="查 >= 此日"),
    target_etd_to: date | None = Query(None, description="查 <= 此日"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[ForecastRead]:
    org = await get_default_organization(db)
    stmt = select(Forecast).where(Forecast.organization_id == org.id)
    if status:
        try:
            s_enum = ForecastStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
        stmt = stmt.where(Forecast.status == s_enum)
    if source:
        try:
            src_enum = ForecastSource(source)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid source: {source}")
        stmt = stmt.where(Forecast.source == src_enum)
    if customer_id:
        stmt = stmt.where(Forecast.customer_id == customer_id)
    if pol:
        stmt = stmt.where(Forecast.pol == pol)
    if pod:
        stmt = stmt.where(Forecast.pod == pod)
    if target_etd_from:
        stmt = stmt.where(Forecast.target_etd >= target_etd_from)
    if target_etd_to:
        stmt = stmt.where(Forecast.target_etd <= target_etd_to)
    stmt = stmt.order_by(Forecast.target_etd.asc(), Forecast.created_at.asc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [ForecastRead.model_validate(r) for r in rows]


@router.get("/weekly", response_model=ForecastWeeklySummary)
async def get_weekly_summary(
    week_start: date | None = Query(None, description="ISO 周一, 默认本周"),
    cut_off_alert_days: int = Query(3, ge=1, le=14),
    db: AsyncSession = Depends(db_session),
) -> ForecastWeeklySummary:
    org = await get_default_organization(db)
    ws = week_start or iso_week_start(date.today())
    data = await weekly_summary(
        db, org.id, week_start=ws, cut_off_alert_days=cut_off_alert_days,
    )
    return ForecastWeeklySummary(**data)


@router.get("/{forecast_id}", response_model=ForecastRead)
async def get_forecast(
    forecast_id: str, db: AsyncSession = Depends(db_session)
) -> ForecastRead:
    org = await get_default_organization(db)
    f = (await db.execute(
        select(Forecast).where(
            Forecast.id == forecast_id,
            Forecast.organization_id == org.id,
        )
    )).scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="forecast not found")
    return ForecastRead.model_validate(f)


@router.patch("/{forecast_id}", response_model=ForecastRead)
async def update_forecast(
    forecast_id: str,
    payload: ForecastUpdate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ForecastRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    f = (await db.execute(
        select(Forecast).where(
            Forecast.id == forecast_id,
            Forecast.organization_id == org.id,
        )
    )).scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="forecast not found")
    if f.status == ForecastStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="cancelled forecast cannot be updated")

    before = {"status": f.status.value, "shipment_id": f.shipment_id, "notes": f.notes}
    if payload.status:
        f.status = ForecastStatus(payload.status)
    if payload.shipment_id is not None:
        f.shipment_id = payload.shipment_id
    if payload.notes is not None:
        f.notes = payload.notes
    await db.commit()
    await db.refresh(f)

    after = {"status": f.status.value, "shipment_id": f.shipment_id, "notes": f.notes}
    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="forecast",
        entity_id=f.id,
        action="update",
        actor=actor,
        field_changes={"before": before, "after": after},
        reason=payload.reason,
    )
    await db.commit()
    return ForecastRead.model_validate(f)


# ========== 配载 / 取消 ==========


@router.post("/{forecast_id}/allocate", response_model=ForecastRead)
async def allocate_forecast_endpoint(
    forecast_id: str,
    payload: ForecastAllocateRequest,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ForecastRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    try:
        f = await allocate_forecast(
            db, forecast_id=forecast_id, shipment_id=payload.shipment_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(f)

    # 自动异常件检测 (forecast 字段 vs actual Shipment)
    exceptions_created = await auto_detect_forecast_exceptions(
        db, organization_id=org.id, forecast_id=f.id,
    )
    if exceptions_created:
        logger.info(f"forecast {f.id} allocate triggered {len(exceptions_created)} exception(s)")
    await db.commit()

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="forecast",
        entity_id=f.id,
        action="allocate",
        actor=actor,
        field_changes={"shipment_id": payload.shipment_id, "exceptions_created": len(exceptions_created)},
        reason=f"allocate forecast to shipment {payload.shipment_id}",
    )
    await db.commit()
    return ForecastRead.model_validate(f)


@router.post("/{forecast_id}/cancel", response_model=ForecastRead)
async def cancel_forecast_endpoint(
    forecast_id: str,
    payload: ForecastCancelRequest,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ForecastRead:
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    try:
        f = await cancel_forecast(db, forecast_id=forecast_id, reason=payload.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(f)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="forecast",
        entity_id=f.id,
        action="cancel",
        actor=actor,
        field_changes={"reason": payload.reason},
        reason=payload.reason,
    )
    await db.commit()
    return ForecastRead.model_validate(f)
