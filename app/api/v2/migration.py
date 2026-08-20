"""v0.5 初始化 monitoring endpoints

- GET /api/v2/migration/status: v0.4 vs v0.5 row count + LegacyEntityMap 统计 + 未迁实体
- GET /api/v2/migration/api-stats: 实时 v0.4 vs v0.5 API 调用量 (从 APIStatsMiddleware)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.middleware import api_stats
from app.core.organization_context import get_default_organization
from app.models.legacy_entity_map import LegacyEntityMap

router = APIRouter()


# ========== v0.4 实体表 (v0.4 model 表名) ==========

V04_TABLES = {
    "agents": "Agent",
    "bookings": "Booking",
    "sos": "SO",
    "tracking_events": "TrackingEvent",
    "email_logs": "EmailLog",
    "bills": "Bill",
    "email_templates": "EmailTemplate",
    "email_ingestions": "EmailIngestion",
    "processed_emails": "ProcessedEmail",
}


# ========== v0.5 实体表 ==========

V05_TABLES = {
    "organizations": "Organization",
    "partners": "Partner",
    "audit_logs": "AuditLog",
    "shipments": "Shipment",
    "booking_requests": "BookingRequest",
    "booking_confirmations": "BookingConfirmation",
    "containers": "Container",
    "documents": "Document",
    "document_extractions": "DocumentExtraction",
    "email_threads": "EmailThread",
    "email_messages": "EmailMessage",
    "milestones": "Milestone",
    "tasks": "Task",
    "operational_exceptions": "OperationalException",
    "legacy_entity_maps": "LegacyEntityMap",
    "bills_v5": "BillV5",
}


@router.get("/status", response_model=dict)
async def get_migration_status(
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """v0.4 vs v0.5 row count + LegacyEntityMap 统计 + 未迁实体

    返:
    - v0.4_counts: {table: count}
    - v0.5_counts: {table: count}
    - legacy_map: {v04_type: count, v05_type: count}
    - unmapped: 未迁 v0.4 booking 数量 (v0.4 booking_id 在 legacy map 找不到 v0.5 shipment)
    - migration_completeness: {v04_type: mapped/total}
    """
    org = await get_default_organization(db)
    org_id = org.id

    v04_counts: dict[str, int] = {}
    for table in V04_TABLES:
        try:
            count = (await db.execute(
                select(func.count()).select_from(__import__("sqlalchemy").text(table))
            )).scalar() or 0
            v04_counts[table] = count
        except Exception as e:
            logger.warning("v0.4 表 %s 查询失败: %s", table, e)
            v04_counts[table] = -1

    v05_counts: dict[str, int] = {}
    for table in V05_TABLES:
        try:
            # organizations 表本身没 organization_id 字段 (其他表是 FK)
            if table == "organizations":
                count = (await db.execute(
                    select(func.count()).select_from(__import__("sqlalchemy").text(table))
                )).scalar() or 0
            else:
                count = (await db.execute(
                    select(func.count()).select_from(__import__("sqlalchemy").text(table))
                    .where(__import__("sqlalchemy").text(f"{table}.organization_id = :oid")).params(oid=org_id)
                )).scalar() or 0
            v05_counts[table] = count
        except Exception as e:
            logger.warning("v0.5 表 %s 查询失败: %s", table, e)
            v05_counts[table] = -1

    # LegacyEntityMap 统计
    legacy_map_by_v04: dict[str, int] = {}
    legacy_map_by_v05: dict[str, int] = {}
    rows = (await db.execute(
        select(LegacyEntityMap).where(LegacyEntityMap.organization_id == org_id)
    )).scalars().all()
    for m in rows:
        legacy_map_by_v04[m.v04_type] = legacy_map_by_v04.get(m.v04_type, 0) + 1
        legacy_map_by_v05[m.v05_type] = legacy_map_by_v05.get(m.v05_type, 0) + 1

    # 迁移完整度
    v04_to_expected = {
        "agent": "partner",
        "booking": "shipment",
        "so": "document",  # so 可能同时映射到 document + booking_confirmation
        "tracking_event": "milestone",
        "email_log": "email_message",
        "bill": "bill",
    }
    completeness: dict[str, dict[str, int]] = {}
    for v04_type, v05_type in v04_to_expected.items():
        total = v04_counts.get(v04_type + ("s" if not v04_type.endswith("s") else ""), 0)
        if v04_type == "so":
            total = v04_counts.get("sos", 0)
        elif v04_type == "tracking_event":
            total = v04_counts.get("tracking_events", 0)
        elif v04_type == "email_log":
            total = v04_counts.get("email_logs", 0)
        mapped = legacy_map_by_v04.get(v04_type, 0)
        completeness[v04_type] = {
            "total": max(total, 0),
            "mapped": mapped,
            "completeness": round(mapped / total, 2) if total > 0 else 1.0,
        }

    return {
        "organization_id": org_id,
        "v0.4_counts": v04_counts,
        "v0.5_counts": v05_counts,
        "legacy_map_by_v04_type": legacy_map_by_v04,
        "legacy_map_by_v05_type": legacy_map_by_v05,
        "migration_completeness": completeness,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api-stats", response_model=dict)
async def get_api_stats() -> dict[str, Any]:
    """实时 v0.4 vs v0.5 API 调用量 (从 APIStatsMiddleware 内存)

    返:
    - v1_total / v2_total / other_total
    - by_endpoint: {method:path_prefix: {count, error_count, avg_ms, ...}}
    - started_at
    """
    by_endpoint_out = {}
    for key, stat in api_stats.by_endpoint.items():
        avg_ms = stat.total_ms / stat.count if stat.count > 0 else 0.0
        by_endpoint_out[key] = {
            "method": stat.method,
            "path_prefix": stat.path_prefix,
            "version": stat.version,
            "count": stat.count,
            "error_count": stat.error_count,
            "avg_ms": round(avg_ms, 2),
            "last_called_at": stat.last_called_at.isoformat() if stat.last_called_at else None,
        }

    # 按版本聚合
    by_version_count: dict[str, int] = {}
    for stat in api_stats.by_endpoint.values():
        by_version_count[stat.version] = by_version_count.get(stat.version, 0) + stat.count

    total = api_stats.v1_total + api_stats.v2_total + api_stats.other_total
    return {
        "v1_total": api_stats.v1_total,
        "v2_total": api_stats.v2_total,
        "other_total": api_stats.other_total,
        "total": total,
        "v1_pct": round(api_stats.v1_total / total, 2) if total > 0 else 0.0,
        "v2_pct": round(api_stats.v2_total / total, 2) if total > 0 else 0.0,
        "by_endpoint": by_endpoint_out,
        "by_version_count": by_version_count,
        "started_at": api_stats.started_at.isoformat(),
    }
