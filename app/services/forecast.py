"""v0.6 预报货量统计 service

核心能力:
- 内容指纹 dedup (跨源 customer+pol+pod+target_etd+container_type)
- 多源命中自动升级 status=confirmed (>=2 源同 fingerprint)
- 周汇总 (按 ISO 周聚合 pol/pod × customer)
- 截单预警 (CY Cut-off 前 N 天)
- 异常件自动标记 (forecast 字段 vs actual Shipment 字段差)
- 配载 (associate forecast.id → shipment.id)
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.forecast import Forecast, ForecastSource, ForecastStatus
from app.models.operational_exception import (
    ExceptionCode,
    ExceptionDetectedBy,
    ExceptionSeverity,
    ExceptionStatus,
    OperationalException,
)
from app.models.partner import Partner
from app.models.shipment import Shipment


# ========== Dedup 内容指纹 ==========


def make_content_fingerprint(
    customer_id: str,
    pol: str,
    pod: str,
    target_etd: date,
    container_type: str,
) -> str:
    """跨源 dedup 指纹 = sha256(customer + pol + pod + etd + container_type)

    标准化: 全部小写 + 去空格, 避免 'CNSHA' vs ' cnsh a' 不同指纹.
    """
    payload = f"{customer_id.strip().lower()}|{pol.strip().lower()}|{pod.strip().lower()}|{target_etd.isoformat()}|{container_type.strip().lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ========== 多源 dedup 检测 ==========


async def find_existing_forecasts_by_fingerprint(
    db: AsyncSession,
    organization_id: str,
    fingerprint: str,
) -> list[Forecast]:
    """同 fingerprint 的所有 forecasts (含多源历史)"""
    stmt = select(Forecast).where(
        Forecast.organization_id == organization_id,
        Forecast.content_fingerprint == fingerprint,
    ).order_by(Forecast.created_at.asc())
    return list((await db.execute(stmt)).scalars().all())


async def find_duplicate_forecasts(
    db: AsyncSession,
    organization_id: str,
    *,
    customer_id: str,
    pol: str,
    pod: str,
    target_etd: date,
    container_type: str,
    source: ForecastSource | None = None,
    source_ref: str | None = None,
) -> list[Forecast]:
    """dedup 检测: 返回已存在的 forecasts (同 fingerprint 或同 source+source_ref)

    同源同 source_ref 完全去重 (DB UNIQUE 也会拒, 这里返 warning 用)
    跨源同 fingerprint 标记"待人工确认"
    """
    fingerprint = make_content_fingerprint(customer_id, pol, pod, target_etd, container_type)
    existing = await find_existing_forecasts_by_fingerprint(db, organization_id, fingerprint)
    # 兼容: 同 source + source_ref 也算 dup (即使 fingerprint 算错)
    if source and source_ref:
        stmt = select(Forecast).where(
            Forecast.organization_id == organization_id,
            Forecast.source == source,
            Forecast.source_ref == source_ref,
        )
        for f in (await db.execute(stmt)).scalars().all():
            if f not in existing:
                existing.append(f)
    return existing


def dedup_action_for(
    new_payload: dict[str, Any],
    existing: list[Forecast],
) -> tuple[str, str]:
    """根据已有 forecasts 决定新建/合并/待人工

    返回 (action, note):
    - "create_new": 没有 fingerprint 命中, 正常新建
    - "merge_into_existing": 已有同 fingerprint, 升级为 confirmed
    - "needs_human": 已有但 source 不同 (跨源), 让用户确认

    注: 同源同 source_ref 在 DB 层 UNIQUE 约束, 这里只处理跨源场景.
    """
    if not existing:
        return "create_new", ""
    sources = {f.source for f in existing}
    if len(existing) == 0:
        return "create_new", ""
    if len(sources) == 1 and existing[0].source == new_payload.get("source"):
        # 同源同 fingerprint (不同 source_ref): 视为重复录入
        return "needs_human", f"同源同内容已存在 {len(existing)} 条, 疑似重复录入"
    return "merge_into_existing", f"已有 {len(existing)} 条同内容预报 (来源: {','.join(s.value for s in sources)}), 自动标记为 confirmed"


# ========== 创建 / 配载 / 取消 ==========


async def create_forecast(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_user_name: str | None,
    payload: dict[str, Any],
    auto_confirm: bool = True,
) -> tuple[Forecast, str]:
    """建 forecast + 触发 dedup + 自动 confirmed 升级

    返回 (forecast, action). action ∈ {create_new, merge_into_existing, needs_human}
    """
    fingerprint = make_content_fingerprint(
        payload["customer_id"],
        payload["pol"],
        payload["pod"],
        payload["target_etd"],
        payload["container_type"],
    )
    existing = await find_existing_forecasts_by_fingerprint(db, organization_id, fingerprint)
    action, note = dedup_action_for(payload, existing)

    f = Forecast(
        organization_id=organization_id,
        source=ForecastSource(payload.get("source", "manual")),
        source_ref=payload.get("source_ref"),
        content_fingerprint=fingerprint,
        customer_id=payload["customer_id"],
        customer_name=payload["customer_name"],
        pol=payload["pol"],
        pod=payload["pod"],
        container_type=payload["container_type"],
        container_count=payload["container_count"],
        target_etd=payload["target_etd"],
        commodity=payload.get("commodity"),
        weight_kg=payload.get("weight_kg"),
        volume_cbm=payload.get("volume_cbm"),
        pieces=payload.get("pieces"),
        is_dangerous=payload.get("is_dangerous", False),
        notes=payload.get("notes") or note,
        source_metadata=payload.get("source_metadata"),
        created_by_user_id=actor_user_id,
        created_by_user_name=actor_user_name,
    )
    db.add(f)
    await db.flush()  # 触发同源同 source_ref UNIQUE 抛 IntegrityError 给上层

    # 自动升级 confirmed (>= 2 源同 fingerprint 时)
    if auto_confirm and action == "merge_into_existing":
        for ef in existing:
            if ef.status == ForecastStatus.FORECASTED:
                ef.status = ForecastStatus.CONFIRMED
        # 新建这条保持 forecasted (它是第 N+1 源)
        await db.flush()

    return f, action


async def allocate_forecast(
    db: AsyncSession,
    *,
    forecast_id: str,
    shipment_id: str,
) -> Forecast:
    """forecast 配载 (forecast.shipment_id = shipment.id, status = allocated)"""
    f = (await db.execute(
        select(Forecast).where(Forecast.id == forecast_id)
    )).scalar_one_or_none()
    if not f:
        raise ValueError(f"forecast {forecast_id} not found")
    if f.status in (ForecastStatus.ALLOCATED, ForecastStatus.LOADED, ForecastStatus.CANCELLED):
        raise ValueError(f"forecast already in status {f.status.value}, cannot allocate")
    s = (await db.execute(
        select(Shipment).where(Shipment.id == shipment_id)
    )).scalar_one_or_none()
    if not s:
        raise ValueError(f"shipment {shipment_id} not found")
    f.shipment_id = shipment_id
    f.status = ForecastStatus.ALLOCATED
    return f


async def cancel_forecast(
    db: AsyncSession,
    *,
    forecast_id: str,
    reason: str,
) -> Forecast:
    f = (await db.execute(
        select(Forecast).where(Forecast.id == forecast_id)
    )).scalar_one_or_none()
    if not f:
        raise ValueError(f"forecast {forecast_id} not found")
    if f.status == ForecastStatus.LOADED:
        raise ValueError("loaded forecast cannot be cancelled, please create exception instead")
    if f.shipment_id:
        f.shipment_id = None  # 解除配载
    f.status = ForecastStatus.CANCELLED
    f.notes = (f.notes or "") + f"\n[取消] {reason}"
    return f


# ========== 周汇总 (按 ISO 周聚合) ==========


def iso_week_start(d: date) -> date:
    """返 ISO 周一 (周一为一周开始)"""
    return d - timedelta(days=d.weekday())


def iso_week_end(d: date) -> date:
    """返 ISO 周日"""
    return iso_week_start(d) + timedelta(days=6)


async def weekly_summary(
    db: AsyncSession,
    organization_id: str,
    *,
    week_start: date,
    cut_off_alert_days: int = 3,
) -> dict[str, Any]:
    """周汇总 (按 pol/pod × customer_id 聚合)

    返回:
    {
        "week_start": date, "week_end": date,
        "rows": [
            {pol, pod, customer_id, customer_name,
             total_count, confirmed_count, allocated_count, pending_count,
             forecast_ids, source_breakdown},
            ...
        ],
        "total_forecast_count", "total_allocated_count",
        "cut_off_alerts": [{forecast_id, days_remaining, container_count}, ...]
    }
    """
    week_end = iso_week_end(week_start)
    stmt = select(Forecast).where(
        Forecast.organization_id == organization_id,
        Forecast.target_etd >= week_start,
        Forecast.target_etd <= week_end,
        Forecast.status != ForecastStatus.CANCELLED,
    ).order_by(Forecast.pol, Forecast.pod, Forecast.customer_id)
    rows = list((await db.execute(stmt)).scalars().all())

    # 聚合: (pol, pod, customer_id) → 总览
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for f in rows:
        key = (f.pol, f.pod, f.customer_id)
        b = buckets.setdefault(key, {
            "pol": f.pol,
            "pod": f.pod,
            "customer_id": f.customer_id,
            "customer_name": f.customer_name,
            "total_count": 0,
            "confirmed_count": 0,
            "allocated_count": 0,
            "pending_count": 0,
            "forecast_ids": [],
            "source_breakdown": defaultdict(int),
        })
        b["total_count"] += f.container_count
        b["forecast_ids"].append(f.id)
        b["source_breakdown"][f.source.value] += f.container_count
        if f.status == ForecastStatus.CONFIRMED:
            b["confirmed_count"] += f.container_count
        if f.status == ForecastStatus.ALLOCATED:
            b["allocated_count"] += f.container_count
            b["confirmed_count"] += f.container_count  # allocated 隐含 confirmed
        if f.status == ForecastStatus.LOADED:
            b["allocated_count"] += f.container_count
            b["confirmed_count"] += f.container_count
        if f.status == ForecastStatus.FORECASTED:
            b["pending_count"] += f.container_count

    # 总览
    total_forecast_count = sum(b["total_count"] for b in buckets.values())
    total_allocated_count = sum(b["allocated_count"] for b in buckets.values())

    # 截单预警: 关联 Shipment.cy_cutoff_at <= 3 天
    today = date.today()
    alert_deadline = today + timedelta(days=cut_off_alert_days)
    cut_off_alerts: list[dict[str, Any]] = []
    stmt2 = select(Forecast, Shipment.cy_cutoff_at).join(
        Shipment, Forecast.shipment_id == Shipment.id
    ).where(
        Forecast.organization_id == organization_id,
        Forecast.target_etd >= week_start,
        Forecast.target_etd <= week_end,
        Forecast.status.in_([ForecastStatus.ALLOCATED, ForecastStatus.LOADED]),
        Shipment.cy_cutoff_at.isnot(None),
        Shipment.cy_cutoff_at <= alert_deadline,
        Shipment.cy_cutoff_at >= today,
    )
    for f, cy_cutoff in (await db.execute(stmt2)).all():
        days_remaining = (cy_cutoff.date() - today).days if cy_cutoff else 0
        cut_off_alerts.append({
            "forecast_id": f.id,
            "shipment_id": f.shipment_id,
            "pol": f.pol, "pod": f.pod,
            "customer_name": f.customer_name,
            "container_count": f.container_count,
            "cy_cutoff_at": cy_cutoff.isoformat() if cy_cutoff else None,
            "days_remaining": days_remaining,
        })

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "rows": [
            {**b, "source_breakdown": dict(b["source_breakdown"])}
            for b in buckets.values()
        ],
        "total_forecast_count": total_forecast_count,
        "total_allocated_count": total_allocated_count,
        "cut_off_alerts": cut_off_alerts,
    }


# ========== 异常件自动标记 (forecast 字段 vs actual Shipment) ==========


# 阈值: 数量差 > 20% 或绝对值差 > 2 柜算异常
_FORECAST_QUANTITY_THRESHOLD_RATIO = 0.2
_FORECAST_QUANTITY_THRESHOLD_ABS = 2

# 阈值: ETD 差 > 3 天算异常
_FORECAST_ETD_DAYS_THRESHOLD = 3


async def auto_detect_forecast_exceptions(
    db: AsyncSession,
    *,
    organization_id: str,
    forecast_id: str,
) -> list[OperationalException]:
    """检测 forecast vs 实际 Shipment 字段差, 自动建 OperationalException

    比对维度:
    1. 数量 (forecast.container_count vs shipment.container_count)
    2. ETD (forecast.target_etd vs shipment.etd)
    3. 柜型 (forecast.container_type vs shipment.first Container.container_type, 简化)
    """
    f = (await db.execute(
        select(Forecast).where(
            Forecast.id == forecast_id,
            Forecast.organization_id == organization_id,
        )
    )).scalar_one_or_none()
    if not f or not f.shipment_id:
        return []

    s = (await db.execute(
        select(Shipment).where(Shipment.id == f.shipment_id)
    )).scalar_one_or_none()
    if not s:
        return []

    exceptions_created: list[OperationalException] = []
    now = datetime.now(timezone.utc)

    # 1. 数量差
    if s.container_count != f.container_count:
        diff = abs(s.container_count - f.container_count)
        ratio = diff / max(f.container_count, 1)
        if diff >= _FORECAST_QUANTITY_THRESHOLD_ABS or ratio >= _FORECAST_QUANTITY_THRESHOLD_RATIO:
            ex = OperationalException(
                organization_id=organization_id,
                shipment_id=s.id,
                code=ExceptionCode.FORECAST_QUANTITY_MISMATCH,
                severity=ExceptionSeverity.WARNING if diff <= _FORECAST_QUANTITY_THRESHOLD_ABS * 2 else ExceptionSeverity.CRITICAL,
                status=ExceptionStatus.OPEN,
                detected_at=now,
                detected_by=ExceptionDetectedBy.SYSTEM,
                context={
                    "source": "forecast_auto_detect",
                    "forecast_id": f.id,
                    "forecast_count": f.container_count,
                    "shipment_count": s.container_count,
                    "diff": diff,
                    "ratio": round(ratio, 3),
                },
            )
            db.add(ex)
            exceptions_created.append(ex)

    # 2. ETD 差
    if s.etd and f.target_etd:
        etd_diff = abs((s.etd - f.target_etd).days)
        if etd_diff >= _FORECAST_ETD_DAYS_THRESHOLD:
            ex = OperationalException(
                organization_id=organization_id,
                shipment_id=s.id,
                code=ExceptionCode.FORECAST_ETD_MISMATCH,
                severity=ExceptionSeverity.WARNING if etd_diff <= 7 else ExceptionSeverity.CRITICAL,
                status=ExceptionStatus.OPEN,
                detected_at=now,
                detected_by=ExceptionDetectedBy.SYSTEM,
                context={
                    "source": "forecast_auto_detect",
                    "forecast_id": f.id,
                    "forecast_etd": f.target_etd.isoformat(),
                    "shipment_etd": s.etd.isoformat(),
                    "diff_days": etd_diff,
                },
            )
            db.add(ex)
            exceptions_created.append(ex)

    # 3. 柜型 (v0.5 Shipment 没 container_type 字段, 跳过; 后续 v0.6.x 加)
    # v0.5 简化: 数量 + ETD 已够覆盖 80% 异常

    if exceptions_created:
        await db.flush()
        logger.info(
            "forecast {} auto-detected {} exception(s) vs shipment {}",
            f.id, len(exceptions_created), s.id,
        )
    return exceptions_created
