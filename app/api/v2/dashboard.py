"""Dashboard endpoint - 4 卡片统计 (主列表顶部)"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.organization_context import get_default_organization
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
