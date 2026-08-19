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
from app.api.v1.router import api_router
from app.config import settings
from app.core.logging import setup_logging
from app.database import init_db
from app.utils.bootstrap import seed_default_templates


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
    yield
    logger.info("=== {} 关闭 ===", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="货代订舱系统: SO OCR 识别 + 邮件订舱 + 账单 + 代理管理",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

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
            "api": "/api/v1",
        }
    )


app.include_router(api_router, prefix="/api/v1")

# 静态资源 (uploads) - 仅供下载, 不开放上传
if settings.upload_dir.exists():
    app.mount("/files", StaticFiles(directory=str(settings.upload_dir)), name="files")
