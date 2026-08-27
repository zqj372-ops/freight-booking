"""v0.6.3 头程时效 service

核心功能:
- update_eta: 操作员/系统更新 ETA, 记历史 + 触发延误异常
- detect_eta_delays: 扫描所有 in-transit shipment, 检测:
  1. ETA 变更 (比上次推迟) → ETA_DELAYED
  2. ETA 已过 N 天仍未卸货 → ETA_PASSED_UNLOADED
  3. ETA 已过 N 天仍未派送 → ETA_PASSED_DELIVERED
- eta_approaching: 找 ETA 临近 7/3/1 天的 shipment (没卸货/没派送)
- build_transit_board: 头程看板数据 (in_transit / delayed / upcoming)

阈值 (常量, 可调):
- ETA_DELTA_THRESHOLD: 3 天 (推后 >= 3 天算延误, 否则正常修订)
- ETA_PASSED_UNLOAD_DAYS: 2 天 (ETA 已过 2 天仍未卸货)
- ETA_PASSED_DELIVER_DAYS: 5 天 (ETA 已过 5 天仍未派送)
- ETA_APPROACHING: [7, 3, 1] (临近 7/3/1 天)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operational_exception import (
    ExceptionCode,
    ExceptionDetectedBy,
    ExceptionSeverity,
    ExceptionStatus,
    OperationalException,
)
from app.models.shipment import Shipment, ShipmentStage
from app.models.transit_time import (
    EtaUpdate,
    EtaUpdateReason,
    EtaUpdateSource,
)


# ========== 阈值常量 ==========

# ETA 推后 N 天才算延误
ETA_DELTA_THRESHOLD_DAYS = 3
# ETA 已过 N 天仍未卸货
ETA_PASSED_UNLOAD_DAYS = 2
# ETA 已过 N 天仍未派送
ETA_PASSED_DELIVER_DAYS = 5
# 临近 ETA 提醒: 7/3/1 天
ETA_APPROACHING_DAYS = [7, 3, 1]


# ========== ETA 更新 ==========


async def update_eta(
    db: AsyncSession,
    shipment: Shipment,
    new_eta: date,
    reason: EtaUpdateReason = EtaUpdateReason.OTHER,
    change_reason: str | None = None,
    source: EtaUpdateSource = EtaUpdateSource.MANUAL,
    user_id: str | None = None,
    user_name: str | None = None,
    related_document_id: str | None = None,
    auto_create_exception: bool = True,
) -> EtaUpdate:
    """更新 ETA, 记历史, 必要时建异常

    v0.6.3 业务规则:
    - 第一次设 ETA (old_eta is None) → reason=initial, 不建异常
    - 推后 >= ETA_DELTA_THRESHOLD_DAYS (3 天) → 建 ETA_DELAYED 异常
    - 提前 (new < old) → 不建异常 (算提前到达, 是好事)
    - 推后 < 3 天 → 不建异常 (正常修订)
    """
    old_eta = shipment.eta
    delta_days = 0
    if old_eta and new_eta:
        delta_days = (new_eta - old_eta).days

    # 1. 写历史
    eta_update = EtaUpdate(
        id=str(uuid.uuid4()),
        organization_id=shipment.organization_id,
        shipment_id=shipment.id,
        old_eta=old_eta,
        new_eta=new_eta,
        delta_days=delta_days,
        source=source,
        reason=reason,
        change_reason=change_reason,
        related_document_id=related_document_id,
        updated_by_user_id=user_id,
        updated_by_user_name=user_name,
    )
    db.add(eta_update)
    await db.flush()

    # 2. 更新 Shipment.eta
    shipment.eta = new_eta

    # 3. 决定是否建异常
    triggered_exception_id: str | None = None
    if auto_create_exception and old_eta is not None and delta_days >= ETA_DELTA_THRESHOLD_DAYS:
        ex = await _create_eta_exception(
            db, shipment, old_eta, new_eta, delta_days, reason, change_reason,
        )
        if ex:
            triggered_exception_id = ex.id
            eta_update.triggered_exception_id = triggered_exception_id
            await db.flush()

    logger.info(
        f"shipment {shipment.id[:8]} ETA 更新: "
        f"{old_eta} → {new_eta} ({delta_days:+d}d), 触发异常: {triggered_exception_id}"
    )
    return eta_update


async def _create_eta_exception(
    db: AsyncSession,
    shipment: Shipment,
    old_eta: date,
    new_eta: date,
    delta_days: int,
    reason: EtaUpdateReason,
    change_reason: str | None,
) -> OperationalException | None:
    """建 ETA_DELAYED 异常 (推后 >= 3 天)"""
    # 已有 open 的 ETA_DELAYED 异常不重复建
    existing = (
        await db.execute(
            select(OperationalException).where(
                and_(
                    OperationalException.shipment_id == shipment.id,
                    OperationalException.code == ExceptionCode.ETA_DELAYED,
                    OperationalException.status == ExceptionStatus.OPEN,
                )
            )
        )
    ).scalar_one_or_none()
    if existing:
        logger.debug(f"shipment {shipment.id[:8]} 已有 open ETA_DELAYED 异常, 跳过新建")
        return None

    ex = OperationalException(
        id=str(uuid.uuid4()),
        organization_id=shipment.organization_id,
        shipment_id=shipment.id,
        code=ExceptionCode.ETA_DELAYED,
        severity=ExceptionSeverity.CRITICAL if delta_days >= 7 else ExceptionSeverity.WARNING,
        status=ExceptionStatus.OPEN,
        detected_at=datetime.now(timezone.utc),
        detected_by=ExceptionDetectedBy.SYSTEM,
        context={
            "source": "eta_update",
            "old_eta": old_eta.isoformat(),
            "new_eta": new_eta.isoformat(),
            "delta_days": delta_days,
            "reason": reason.value,
            "change_reason": change_reason,
        },
    )
    db.add(ex)
    await db.flush()
    logger.info(
        f"shipment {shipment.id[:8]} ETA 推后 {delta_days} 天, 自动建 ETA_DELAYED 异常 {ex.id[:8]}"
    )

    # v0.6.1 打通: 异常创建自动 enqueue AI 跟进
    try:
        from app.services.exception_followup import on_exception_created
        await on_exception_created(db, ex)
    except Exception as e:
        logger.warning(f"ETA 异常 AI 跟进 enqueue 失败: {e}")

    return ex


# ========== 定时扫描: ETA 已过未卸货 / 未派送 ==========


async def detect_eta_delays(
    db: AsyncSession, today: date | None = None
) -> list[OperationalException]:
    """扫描所有已 DEPARTED 但 ETA 已过 / 未卸货 / 未派送的 shipment

    返回新建的异常列表
    """
    if today is None:
        today = date.today()
    new_exceptions: list[OperationalException] = []

    # 找 stage=departed 的 shipment
    shipments = (
        await db.execute(
            select(Shipment).where(
                and_(
                    Shipment.stage == ShipmentStage.DEPARTED,
                    Shipment.eta.isnot(None),
                    Shipment.eta < today,
                )
            )
        )
    ).scalars().all()

    for s in shipments:
        if s.eta is None:
            continue
        days_passed = (today - s.eta).days

        # 检查 milestone
        from app.models.milestone import Milestone, MilestoneCode
        ms_codes = set(
            (
                await db.execute(
                    select(Milestone.code).where(Milestone.shipment_id == s.id)
                )
            ).scalars().all()
        )

        has_discharged = MilestoneCode.CONTAINER_DISCHARGED in ms_codes
        has_delivered = MilestoneCode.DELIVERED in ms_codes

        # 1. ETA 已过 N 天仍未卸货
        if not has_discharged and days_passed >= ETA_PASSED_UNLOAD_DAYS:
            ex = await _maybe_create_lifecycle_exception(
                db, s, ExceptionCode.ETA_PASSED_UNLOADED,
                "eta_passed_unloaded",
                {
                    "eta": s.eta.isoformat(),
                    "days_passed": days_passed,
                    "threshold": ETA_PASSED_UNLOAD_DAYS,
                },
            )
            if ex:
                new_exceptions.append(ex)

        # 2. ETA 已过 N 天仍未派送 (且已卸货)
        elif has_discharged and not has_delivered and days_passed >= ETA_PASSED_DELIVER_DAYS:
            ex = await _maybe_create_lifecycle_exception(
                db, s, ExceptionCode.ETA_PASSED_DELIVERED,
                "eta_passed_delivered",
                {
                    "eta": s.eta.isoformat(),
                    "days_passed": days_passed,
                    "threshold": ETA_PASSED_DELIVER_DAYS,
                    "has_discharged": True,
                },
            )
            if ex:
                new_exceptions.append(ex)

    if new_exceptions:
        logger.info(f"ETA 延误检测: 新建 {len(new_exceptions)} 个异常")
    return new_exceptions


async def _maybe_create_lifecycle_exception(
    db: AsyncSession,
    shipment: Shipment,
    code: ExceptionCode,
    source_key: str,
    context: dict[str, Any],
) -> OperationalException | None:
    """生命周期异常 (ETA 已过仍未...): 不重复建"""
    existing = (
        await db.execute(
            select(OperationalException).where(
                and_(
                    OperationalException.shipment_id == shipment.id,
                    OperationalException.code == code,
                    OperationalException.status == ExceptionStatus.OPEN,
                )
            )
        )
    ).scalar_one_or_none()
    if existing:
        return None

    ex = OperationalException(
        id=str(uuid.uuid4()),
        organization_id=shipment.organization_id,
        shipment_id=shipment.id,
        code=code,
        severity=ExceptionSeverity.CRITICAL,
        status=ExceptionStatus.OPEN,
        detected_at=datetime.now(timezone.utc),
        detected_by=ExceptionDetectedBy.SYSTEM,
        context={"source": source_key, **context},
    )
    db.add(ex)
    await db.flush()
    logger.info(
        f"shipment {shipment.id[:8]} 自动建 {code.value} 异常 {ex.id[:8]}"
    )

    # v0.6.1 打通
    try:
        from app.services.exception_followup import on_exception_created
        await on_exception_created(db, ex)
    except Exception as e:
        logger.warning(f"{code.value} 异常 AI 跟进 enqueue 失败: {e}")
    return ex


# ========== 头程看板 ==========


async def build_transit_board(
    db: AsyncSession, today: date | None = None
) -> dict[str, Any]:
    """构建头程看板数据"""
    if today is None:
        today = date.today()

    # 找所有 in-transit + 还未 shipped 的
    in_transit_stages = [
        ShipmentStage.DRAFT,
        ShipmentStage.BOOKING_IN_PROGRESS,
        ShipmentStage.AWAITING_CONFIRMATION,
        ShipmentStage.BOOKED,
        ShipmentStage.CONTAINER_OPERATION,
        ShipmentStage.DOCUMENTATION,
        ShipmentStage.DEPARTED,
    ]
    shipments = (
        await db.execute(
            select(Shipment).where(Shipment.stage.in_(in_transit_stages))
        )
    ).scalars().all()

    overviews: list[dict[str, Any]] = []
    for s in shipments:
        ov = await _build_overview(db, s, today)
        overviews.append(ov)

    # 分类
    by_status: dict[str, int] = {}
    for ov in overviews:
        by_status[ov["status"]] = by_status.get(ov["status"], 0) + 1

    in_transit = [o for o in overviews if o["status"] in ("departed_in_transit", "scheduled")]
    delayed = [o for o in overviews if o["is_delayed"]]
    upcoming_eta_7d = [
        o for o in overviews
        if o["days_to_eta"] is not None and 0 < o["days_to_eta"] <= 7
        and not o["has_discharged"]
    ]
    upcoming_eta_1d = [
        o for o in overviews
        if o["days_to_eta"] is not None and 0 < o["days_to_eta"] <= 1
        and not o["has_discharged"]
    ]

    return {
        "total": len(overviews),
        "by_status": by_status,
        "in_transit": in_transit,
        "delayed": delayed,
        "upcoming_eta_7d": upcoming_eta_7d,
        "upcoming_eta_1d": upcoming_eta_1d,
    }


async def _build_overview(
    db: AsyncSession, s: Shipment, today: date
) -> dict[str, Any]:
    """单 shipment ETA 状态总览"""
    from app.models.milestone import Milestone, MilestoneCode
    ms_codes = set(
        (
            await db.execute(
                select(Milestone.code).where(Milestone.shipment_id == s.id)
            )
        ).scalars().all()
    )

    has_departed = MilestoneCode.DEPARTED in ms_codes
    has_arrived = MilestoneCode.ARRIVED_AT_POD in ms_codes
    has_discharged = MilestoneCode.CONTAINER_DISCHARGED in ms_codes
    has_delivered = MilestoneCode.DELIVERED in ms_codes

    days_to_eta = None
    is_delayed = False
    delay_days = 0
    if s.eta:
        days_to_eta = (s.eta - today).days
        if days_to_eta < 0 and not has_discharged:
            is_delayed = True
            delay_days = abs(days_to_eta)

    # 状态
    if has_delivered:
        status = "delivered"
    elif has_discharged:
        status = "arrived"
    elif has_arrived:
        status = "arrived"
    elif has_departed:
        if is_delayed:
            status = "delayed"
        else:
            status = "departed_in_transit"
    else:
        status = "scheduled"

    # 最新 ETA 变更
    latest_eta_update = (
        await db.execute(
            select(EtaUpdate)
            .where(EtaUpdate.shipment_id == s.id)
            .order_by(EtaUpdate.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # 未关闭异常数
    open_ex_count = (
        await db.execute(
            select(func.count())
            .select_from(OperationalException)
            .where(
                and_(
                    OperationalException.shipment_id == s.id,
                    OperationalException.status == ExceptionStatus.OPEN,
                )
            )
        )
    ).scalar() or 0

    return {
        "shipment_id": s.id,
        "job_no": s.job_no,
        "pol": s.pol,
        "pod": s.pod,
        "stage": s.stage.value,
        "etd": s.etd.isoformat() if s.etd else None,
        "eta": s.eta.isoformat() if s.eta else None,
        "current_carrier": s.current_carrier,
        "status": status,
        "days_to_eta": days_to_eta,
        "is_delayed": is_delayed,
        "delay_days": delay_days,
        "has_departed": has_departed,
        "has_arrived": has_arrived,
        "has_discharged": has_discharged,
        "has_delivered": has_delivered,
        "latest_eta_update": latest_eta_update,  # schema 转换时由 API 层处理
        "open_exception_count": open_ex_count,
    }


async def list_eta_updates(
    db: AsyncSession,
    shipment_id: str,
    limit: int = 50,
) -> list[EtaUpdate]:
    stmt = (
        select(EtaUpdate)
        .where(EtaUpdate.shipment_id == shipment_id)
        .order_by(EtaUpdate.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())
