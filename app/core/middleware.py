"""v0.5 初始化 middleware

- APIStatsMiddleware: 记录每个请求 method + path prefix (v1/v2) + status_code, 内存 dict
- V1ReadOnlyMiddleware: /api/v1 写操作 → 410 Gone (v0.4 deprecated, 只读兼容)

启用方式: app/main.py add_middleware(按顺序: V1ReadOnly → APIStats)
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware


# ========== API 调用统计 ==========


@dataclass
class APICallStat:
    """单个 endpoint 调用统计"""

    method: str
    path_prefix: str  # e.g. "/api/v2/shipments" (去 path param)
    version: str  # "v1" or "v2" or "other"
    count: int = 0
    error_count: int = 0  # status >= 400
    total_ms: float = 0.0
    last_called_at: datetime | None = None


@dataclass
class APIStats:
    """全局 API 调用统计"""

    by_endpoint: Dict[str, APICallStat] = field(default_factory=dict)
    v1_total: int = 0
    v2_total: int = 0
    other_total: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# 全局 singleton (fastapi middleware 共享)
api_stats = APIStats()


def _version_from_path(path: str) -> tuple[str, str]:
    """解析 path → (version, path_prefix)

    e.g. /api/v2/shipments/abc123 → ("v2", "/api/v2/shipments")
         /api/v1/bookings/123/track → ("v1", "/api/v1/bookings")
         /health → ("other", "/health")
         /docs → ("other", "/docs")
    """
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "api" and parts[1] in ("v1", "v2"):
        version = parts[1]
        # path prefix: 取前 3 段 (api/version/resource)
        if len(parts) >= 3:
            path_prefix = "/" + "/".join(parts[:3])
        else:
            path_prefix = "/" + "/".join(parts[:2])
        return version, path_prefix
    return "other", "/" + "/".join(parts[:1]) if parts else "/"


class APIStatsMiddleware(BaseHTTPMiddleware):
    """API 调用统计 middleware

    记录每个请求 method + path prefix + status + duration 到 api_stats singleton
    暴露 GET /api/v2/migration/api-stats 查统计
    """

    async def dispatch(self, request: Request, call_next):
        # /api/v2/migration/api-stats 自己不计 (避免 noise)
        if request.url.path == "/api/v2/migration/api-stats":
            return await call_next(request)

        version, path_prefix = _version_from_path(request.url.path)
        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        # 更新统计
        key = f"{request.method}:{path_prefix}"
        if key not in api_stats.by_endpoint:
            api_stats.by_endpoint[key] = APICallStat(
                method=request.method, path_prefix=path_prefix, version=version,
            )
        stat = api_stats.by_endpoint[key]
        stat.count += 1
        if response.status_code >= 400:
            stat.error_count += 1
        stat.total_ms += duration_ms
        stat.last_called_at = datetime.now(timezone.utc)

        if version == "v1":
            api_stats.v1_total += 1
        elif version == "v2":
            api_stats.v2_total += 1
        else:
            api_stats.other_total += 1

        # 响应头暴露版本统计 (供前端监控)
        response.headers["X-API-Version"] = version
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
        return response


# ========== v0.4 API 只读守卫 ==========


class V1ReadOnlyMiddleware(BaseHTTPMiddleware):
    """/api/v1 写操作 → 410 Gone (v0.4 deprecated)

    保留 GET 用于历史数据查询 (admin / 数据迁移期), 拒绝写操作.
    例外: /api/v1/imap/ingest (v0.5 阶段 2 切 v0.5 IMAP 服务时, v0.4 imap 可停)
    """

    ALLOWED_WRITE_PATHS = (
        "/api/v1/imap/ingest",  # 暂时保留, 后续切 v0.5 imap 后下
    )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/v1") and request.method in ("POST", "PATCH", "DELETE", "PUT"):
            if path in self.ALLOWED_WRITE_PATHS:
                return await call_next(request)
            logger.warning(
                "v0.4 API write rejected: {} {} (use v0.5 /api/v2)",
                request.method, path,
            )
            return Response(
                content=f'{{"detail": "v0.4 API deprecated, use v0.5 /api/v2. path={path}"}}',
                status_code=410,
                media_type="application/json",
                headers={"X-API-Deprecated": "v0.4", "X-API-Use-Instead": "v0.5"},
            )
        return await call_next(request)
