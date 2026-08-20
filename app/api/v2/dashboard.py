"""Dashboard endpoint - 4 卡片统计 + KPI 驾驶舱 (主列表顶部 + 运营页)"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.organization_context import get_default_organization
from app.models.booking_request import BookingRequest
from app.models.partner import Partner
from app.models.shipment import Shipment, ShipmentStage
from app.schemas.shipment import DashboardStats, DashboardTaskItem
from app.services.next_action import derive_dashboard

router = APIRouter()


@router.get("/", response_model=DashboardStats)
async def get_dashboard(
    db: AsyncSession = Depends(db_session),
) -> DashboardStats:
    """4 卡片: 逾期任务 / 今日到期 / 待 SO / 7 日内到港 (1.5.4)"""
    org = await get_default_organization(db)
    stats = await derive_dashboard(db, org.id)
    return DashboardStats(
        overdue_tasks=stats.overdue_tasks,
        due_today=stats.due_today,
        awaiting_so=stats.awaiting_so,
        arriving_within_7d=stats.arriving_within_7d,
        overdue_tasks_top=[DashboardTaskItem(**t) for t in stats.overdue_tasks_top],
        due_today_top=[DashboardTaskItem(**t) for t in stats.due_today_top],
    )


# ========== 阶段 3 第二批: KPI 运营驾驶舱 ==========


# 录入完整度追踪的字段 (非空即视为"录了")
_COMPLETENESS_FIELDS = [
    "customer_name", "customer_ref", "commodity",
    "weight_kg", "volume_cbm", "hs_code", "pieces",
    "etd", "eta", "current_carrier",
    "booking_remark",
]


@router.get("/kpi", response_model=dict)
async def get_kpi_dashboard(
    days: int = Query(90, ge=1, le=365, description="统计最近 N 天 shipment"),
    db: AsyncSession = Depends(db_session),
) -> dict:
    """运营 KPI (运营驾驶舱 KPI tab).

    包含:
    - 总览: shipment 数 / 取消率 / 完成数 / 进行中
    - 录入完整度: 关键字段填充率 (avg)
    - 客户分布: TOP 10 (按 customer_name/customer_partner_id)
    - 航线分布: TOP 10 (按 pol→pod)
    - 船公司份额: TOP 10 (按 current_carrier)
    - 月度趋势: 最近 6 月 shipment 创建数
    - 响应时长: booking_request sent → confirmed 的 P50/P90 (小时)
    """
    org = await get_default_organization(db)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)

    # 1. 总览
    base = select(Shipment).where(Shipment.organization_id == org.id)
    total_shipments = (await db.execute(
        select(func.count()).select_from(Shipment).where(
            Shipment.organization_id == org.id,
            Shipment.created_at >= since,
        )
    )).scalar() or 0
    completed = (await db.execute(
        select(func.count()).select_from(Shipment).where(
            Shipment.organization_id == org.id,
            Shipment.stage == ShipmentStage.COMPLETED,
            Shipment.created_at >= since,
        )
    )).scalar() or 0
    cancelled = (await db.execute(
        select(func.count()).select_from(Shipment).where(
            Shipment.organization_id == org.id,
            Shipment.stage == ShipmentStage.CANCELLED,
            Shipment.created_at >= since,
        )
    )).scalar() or 0
    in_progress = total_shipments - completed - cancelled
    cancel_rate = cancelled / total_shipments if total_shipments > 0 else 0.0

    # 2. 录入完整度 (在 base 子集上算)
    completeness_stats: list[dict] = []
    for fld in _COMPLETENESS_FIELDS:
        col = getattr(Shipment, fld)
        cnt = (await db.execute(
            select(func.count()).select_from(Shipment).where(
                Shipment.organization_id == org.id,
                Shipment.created_at >= since,
                col.isnot(None),
            )
        )).scalar() or 0
        rate = round(cnt / total_shipments, 3) if total_shipments > 0 else 0.0
        completeness_stats.append({
            "field": fld,
            "filled": cnt,
            "total": total_shipments,
            "rate": rate,
        })
    avg_completeness = (
        sum(s["rate"] for s in completeness_stats) / len(completeness_stats)
        if completeness_stats else 0.0
    )

    # 3. 客户分布 (按 customer_name, 取 TOP 10)
    cust_rows = (await db.execute(
        select(
            Shipment.customer_name,
            func.count().label("cnt"),
        )
        .where(
            Shipment.organization_id == org.id,
            Shipment.created_at >= since,
            Shipment.customer_name.isnot(None),
        )
        .group_by(Shipment.customer_name)
        .order_by(func.count().desc())
        .limit(10)
    )).all()
    by_customer = [{"customer_name": cn, "count": cnt} for cn, cnt in cust_rows]

    # 4. 航线分布 (按 pol → pod 拼接, TOP 10)
    route_rows = (await db.execute(
        select(
            Shipment.pol, Shipment.pod,
            func.count().label("cnt"),
        )
        .where(
            Shipment.organization_id == org.id,
            Shipment.created_at >= since,
        )
        .group_by(Shipment.pol, Shipment.pod)
        .order_by(func.count().desc())
        .limit(10)
    )).all()
    by_route = [
        {"route": f"{pol}→{pod}", "pol": pol, "pod": pod, "count": cnt}
        for pol, pod, cnt in route_rows
    ]

    # 5. 船公司份额 (按 current_carrier, TOP 10)
    carrier_rows = (await db.execute(
        select(
            Shipment.current_carrier,
            func.count().label("cnt"),
        )
        .where(
            Shipment.organization_id == org.id,
            Shipment.created_at >= since,
            Shipment.current_carrier.isnot(None),
        )
        .group_by(Shipment.current_carrier)
        .order_by(func.count().desc())
        .limit(10)
    )).all()
    by_carrier = [
        {"carrier": c, "count": cnt}
        for c, cnt in carrier_rows
    ]

    # 6. 月度趋势 (最近 6 个月)
    # SQL: date_trunc('month', created_at) 简化用 year*100+month 分组
    month_expr = func.strftime("%Y%m", Shipment.created_at)
    month_rows = (await db.execute(
        select(
            month_expr.label("ym"),
            func.count().label("cnt"),
        )
        .where(
            Shipment.organization_id == org.id,
            Shipment.created_at >= six_months_ago,
        )
        .group_by(month_expr)
        .order_by(month_expr)
    )).all()
    monthly_trend = [
        {"month": ym, "count": cnt}
        for ym, cnt in month_rows
    ]

    # 7. 响应时长: booking_request.sent_at → confirmed_at (小时)
    #    拿所有有 confirmed_at 的 booking_request
    br_rows = (await db.execute(
        select(
            BookingRequest.sent_at,
            BookingRequest.confirmed_at,
        )
        .where(
            BookingRequest.organization_id == org.id,
            BookingRequest.confirmed_at.isnot(None),
            BookingRequest.sent_at.isnot(None),
        )
    )).all()
    durations_hours: list[float] = []
    for sent, confirmed in br_rows:
        if sent and confirmed:
            delta = (confirmed - sent).total_seconds() / 3600.0
            if delta >= 0:
                durations_hours.append(delta)
    if durations_hours:
        durations_hours.sort()
        p50_idx = int(len(durations_hours) * 0.5)
        p90_idx = min(int(len(durations_hours) * 0.9), len(durations_hours) - 1)
        response_p50 = round(durations_hours[p50_idx], 2)
        response_p90 = round(durations_hours[p90_idx], 2)
        response_avg = round(sum(durations_hours) / len(durations_hours), 2)
    else:
        response_p50 = response_p90 = response_avg = None

    return {
        "days": days,
        "total_shipments": total_shipments,
        "in_progress": in_progress,
        "completed": completed,
        "cancelled": cancelled,
        "cancel_rate": round(cancel_rate, 3),
        "completeness": {
            "avg_rate": round(avg_completeness, 3),
            "fields": completeness_stats,
        },
        "by_customer": by_customer,
        "by_route": by_route,
        "by_carrier": by_carrier,
        "monthly_trend": monthly_trend,
        "response_time": {
            "samples": len(durations_hours),
            "avg_hours": response_avg,
            "p50_hours": response_p50,
            "p90_hours": response_p90,
        },
    }
