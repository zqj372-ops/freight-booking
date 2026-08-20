"""OperationalException 全局 API - v0.5 阶段 3 第二批

运营驾驶舱"异常"tab 数据源:
- GET /api/v2/exceptions/ - 全局列表 (跨 shipment, 按 severity/code 分组)
- GET /api/v2/exceptions/summary - 异常分布统计 (按 code/severity)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.organization_context import get_default_organization
from app.models.operational_exception import (
    ExceptionStatus,
    OperationalException,
)
from app.models.shipment import Shipment
from app.schemas.milestone import OpExRead

router = APIRouter()


@router.get("/", response_model=list[OpExRead])
async def list_global_exceptions(
    status: str | None = Query(None, description="open/resolved/auto_closed"),
    severity: str | None = Query(None, description="info/warning/critical"),
    code: str | None = Query(None, description="异常 code (e.g. cutoff_approaching)"),
    shipment_id: str | None = Query(None),
    days: int = Query(30, ge=1, le=365, description="只看最近 N 天内检测的"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[OpExRead]:
    """跨 shipment 全局异常列表 (运营驾驶舱异常 tab 用).

    默认只返最近 30 天; UI 可改 days 调更长历史.
    """
    org = await get_default_organization(db)
    stmt = select(OperationalException).where(OperationalException.organization_id == org.id)
    if status:
        try:
            s_enum = ExceptionStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
        stmt = stmt.where(OperationalException.status == s_enum)
    if severity:
        stmt = stmt.where(OperationalException.severity == severity)
    if code:
        stmt = stmt.where(OperationalException.code == code)
    if shipment_id:
        stmt = stmt.where(OperationalException.shipment_id == shipment_id)
    # 时间窗口
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = stmt.where(OperationalException.detected_at >= since)
    stmt = stmt.order_by(OperationalException.detected_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [OpExRead.model_validate(r) for r in rows]


@router.get("/summary", response_model=dict)
async def get_exception_summary(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(db_session),
) -> dict:
    """异常分布统计 (按 code + severity + 解决率).

    返回:
    - by_code: list[{code, total, open, resolved, auto_closed}]
    - by_severity: {info, warning, critical: count}
    - resolution_rate: 0.0-1.0 (resolved/total)
    - open_count / total_count
    - by_shipment_top: list[{shipment_id, job_no, open_count}] (TOP 10 异常最多的单)
    """
    org = await get_default_organization(db)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 总览
    total_count = (await db.execute(
        select(func.count())
        .select_from(OperationalException)
        .where(
            OperationalException.organization_id == org.id,
            OperationalException.detected_at >= since,
        )
    )).scalar() or 0
    open_count = (await db.execute(
        select(func.count())
        .select_from(OperationalException)
        .where(
            OperationalException.organization_id == org.id,
            OperationalException.status == ExceptionStatus.OPEN,
            OperationalException.detected_at >= since,
        )
    )).scalar() or 0
    resolved_count = (await db.execute(
        select(func.count())
        .select_from(OperationalException)
        .where(
            OperationalException.organization_id == org.id,
            OperationalException.status == ExceptionStatus.RESOLVED,
            OperationalException.detected_at >= since,
        )
    )).scalar() or 0
    auto_closed_count = (await db.execute(
        select(func.count())
        .select_from(OperationalException)
        .where(
            OperationalException.organization_id == org.id,
            OperationalException.status == ExceptionStatus.AUTO_CLOSED,
            OperationalException.detected_at >= since,
        )
    )).scalar() or 0

    # by_severity
    sev_rows = (await db.execute(
        select(
            OperationalException.severity,
            func.count().label("cnt"),
        )
        .where(
            OperationalException.organization_id == org.id,
            OperationalException.detected_at >= since,
        )
        .group_by(OperationalException.severity)
    )).all()
    by_severity = {s.value: c for s, c in sev_rows}

    # by_code: code + 各状态计数
    code_rows = (await db.execute(
        select(
            OperationalException.code,
            OperationalException.status,
            func.count().label("cnt"),
        )
        .where(
            OperationalException.organization_id == org.id,
            OperationalException.detected_at >= since,
        )
        .group_by(OperationalException.code, OperationalException.status)
    )).all()
    by_code_map: dict[str, dict[str, int]] = {}
    for c, s, cnt in code_rows:
        cv = c.value if hasattr(c, "value") else str(c)
        sv = s.value if hasattr(s, "value") else str(s)
        by_code_map.setdefault(cv, {"code": cv, "total": 0, "open": 0, "resolved": 0, "auto_closed": 0})
        by_code_map[cv]["total"] += cnt
        if sv == "open":
            by_code_map[cv]["open"] += cnt
        elif sv == "resolved":
            by_code_map[cv]["resolved"] += cnt
        elif sv == "auto_closed":
            by_code_map[cv]["auto_closed"] += cnt
    by_code = sorted(by_code_map.values(), key=lambda x: x["total"], reverse=True)

    # by_shipment_top: open 异常最多的前 10 单
    ship_rows = (await db.execute(
        select(
            OperationalException.shipment_id,
            Shipment.job_no,
            func.count().label("cnt"),
        )
        .join(Shipment, OperationalException.shipment_id == Shipment.id)
        .where(
            OperationalException.organization_id == org.id,
            OperationalException.status == ExceptionStatus.OPEN,
            OperationalException.detected_at >= since,
        )
        .group_by(OperationalException.shipment_id, Shipment.job_no)
        .order_by(func.count().desc())
        .limit(10)
    )).all()
    by_shipment_top = [
        {"shipment_id": sid, "job_no": jn, "open_count": cnt}
        for sid, jn, cnt in ship_rows
    ]

    resolution_rate = resolved_count / total_count if total_count > 0 else 1.0

    return {
        "days": days,
        "total_count": total_count,
        "open_count": open_count,
        "resolved_count": resolved_count,
        "auto_closed_count": auto_closed_count,
        "resolution_rate": round(resolution_rate, 3),
        "by_severity": by_severity,
        "by_code": by_code,
        "by_shipment_top": by_shipment_top,
    }
