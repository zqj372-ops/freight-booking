"""APScheduler 定时任务调度

- IMAP 拉取 (imap_poll_interval_seconds)
- v0.6.1 异常 AI 跟进 (exception_fetch_interval_seconds, 默认 2h)
- 未来可加: 邮件重试、对账扫描
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from loguru import logger

from app.config import settings
from app.models.email_ingestion import IngestionSource

_scheduler = None
_running = False


async def _imap_poll_job() -> None:
    """定时任务: 拉取邮件"""
    from app.database import AsyncSessionLocal
    from app.services.imap_service import run_ingestion

    has_real_creds = bool(settings.imap_username and settings.imap_password)
    if not has_real_creds and not settings.imap_mock_mode:
        logger.debug("IMAP 未配置凭据且 mock 关闭, 跳过本次拉取")
        return

    async with AsyncSessionLocal() as db:
        try:
            await run_ingestion(db, source=None)
        except Exception as e:
            logger.exception("定时 IMAP 拉取失败: {}", e)


async def _exception_followup_job() -> None:
    """v0.6.1 定时任务: 跑所有 PENDING 异常抓取 job

    默认每 2h 跑一次, 异常创建后立即可被拉到 (next_run_at = now)
    """
    from app.database import AsyncSessionLocal
    from app.services.exception_followup import schedule_pending_jobs

    async with AsyncSessionLocal() as db:
        try:
            processed = await schedule_pending_jobs(db, max_jobs=50)
            if processed > 0:
                logger.info(f"异常 AI 跟进: 本次处理 {processed} 个 job")
        except Exception as e:
            logger.exception("定时异常跟进失败: {}", e)


async def start_scheduler() -> None:
    """启动后台调度器 (应用启动时调用)"""
    global _scheduler, _running

    if _running:
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.warning("apscheduler 未安装, 定时任务禁用. 装: pip install apscheduler")
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")

    # IMAP 拉取
    if settings.imap_enabled or settings.imap_mock_mode:
        interval = max(60, settings.imap_poll_interval_seconds)
        _scheduler.add_job(
            _imap_poll_job,
            trigger=IntervalTrigger(seconds=interval),
            id="imap_poll",
            name="IMAP 邮件拉取",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc),  # 启动后立即跑一次
        )
        logger.info("IMAP 拉取定时任务已注册: 每 {} 秒", interval)

    # v0.6.1 异常 AI 跟进 (每 2h, 默认, 可改)
    followup_interval = max(300, getattr(settings, "exception_fetch_interval_seconds", 7200))
    _scheduler.add_job(
        _exception_followup_job,
        trigger=IntervalTrigger(seconds=followup_interval),
        id="exception_followup",
        name="异常 AI 跟进",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # 启动后立即跑一次
    )
    logger.info("异常 AI 跟进定时任务已注册: 每 {} 秒", followup_interval)

    _scheduler.start()
    _running = True
    logger.info("后台调度器已启动")


async def stop_scheduler() -> None:
    global _scheduler, _running
    if _scheduler and _running:
        _scheduler.shutdown(wait=False)
        _running = False
        logger.info("后台调度器已停止")
