"""FastAPI 主入口"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app import __version__
from app.api.v1.router import api_router as v1_router
from app.api.v2 import api_router as v2_router
from app.config import settings
from app.core.logging import setup_logging
from app.core.middleware import APIStatsMiddleware, V1ReadOnlyMiddleware
from app.database import init_db
from app.utils.bootstrap import seed_default_templates, seed_default_organization


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("=== {} v{} 启动 ===", settings.app_name, __version__)
    logger.info("env={} debug={}", settings.app_env, settings.debug)
    logger.info("DB: {}", settings.database_url.split("@")[-1])

    # 开发环境自动建表 + 种子数据
    if settings.app_env == "development":
        await init_db()
        await seed_default_templates()
        await seed_default_organization()

    # 启动后台调度器 (IMAP 自动拉取)
    from app.services.scheduler import start_scheduler, stop_scheduler

    await start_scheduler()

    yield

    # 关闭调度器
    await stop_scheduler()
    logger.info("=== {} 关闭 ===", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="货代订舱系统 v0.5: Shipment 聚合根 + 邮件订舱 + SO OCR + 账单",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# 中间件顺序 (FastAPI 倒序执行):
#   1. V1ReadOnly (先于 V2ReadOnly, 因为 V1 在外)
#   2. APIStats
# add_middleware 是反序的: 最后 add 的最先执行
app.add_middleware(APIStatsMiddleware)
app.add_middleware(V1ReadOnlyMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "env": settings.app_env,
    }


@app.get("/", tags=["meta"], include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse(
        {
            "app": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
            "api_v1": "/api/v1 (legacy, 只读)",
            "api_v2": "/api/v2 (v0.5 主用)",
        }
    )


# v0.4 兼容层, 写操作暂不禁用, 阶段 2 切换为只读
app.include_router(v1_router, prefix="/api/v1")
# v0.5 主用
app.include_router(v2_router, prefix="/api/v2")

# 静态资源 (uploads) - 仅供下载, 不开放上传
if settings.upload_dir.exists():
    app.mount("/files", StaticFiles(directory=str(settings.upload_dir)), name="files")
