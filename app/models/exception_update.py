"""v0.6 异常 AI 跟进 数据模型

v0.5 OperationalException 只能静态登记, v0.6 加 2 个新表:
- exception_updates: 异常跟进 timeline (AI 抓取 / 用户备注 / LLM 摘要 / 状态变更)
- exception_fetch_jobs: 后台抓取任务 (carrier 网站 / 邮件 / 企微)
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin


class ExceptionUpdateType(str, enum.Enum):
    """异常 timeline 条目类型"""

    AI_FETCH = "ai_fetch"               # AI 自动抓取 (新进展)
    AI_SUMMARY = "ai_summary"           # LLM 摘要进展
    USER_NOTE = "user_note"             # 用户手动备注
    STATUS_CHANGE = "status_change"     # 状态变更 (open/resolved/auto_closed)
    AI_SUGGESTION = "ai_suggestion"     # AI 建议 (可关闭/需关注)
    USER_RESPONSE = "user_response"     # 用户对 AI 建议的响应 (采纳/拒绝)


class ExceptionUpdateSource(str, enum.Enum):
    """抓取源 (AI fetch 时的来源)"""

    CARRIER_WEBSITE = "carrier_website"  # 船公司公开跟踪网站 (Cosco/MSK/CMA)
    EMAIL = "email"                       # 邮件后续回复 (关联 EmailThread)
    WECHAT = "wechat"                     # 企微后续记录
    USER = "user"                         # 用户手动
    AI_INFERENCE = "ai_inference"         # LLM 推断 (无外部源)


class ExceptionFetchJobStatus(str, enum.Enum):
    """后台抓取任务状态"""

    PENDING = "pending"      # 排队
    RUNNING = "running"      # 执行中
    DONE = "done"            # 成功
    FAILED = "failed"        # 失败 (重试 N 次后)
    CANCELLED = "cancelled"    # 取消 (异常已 close)


class ExceptionUpdate(Base, OrganizationScopedMixin, TimestampMixin):
    """异常跟进 timeline (按时间倒序展示)

    一行 = 一次 update (AI 自动/用户手动/状态变更)
    """

    __tablename__ = "exception_updates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    exception_id: Mapped[str] = mapped_column(
        ForeignKey("operational_exceptions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    update_type: Mapped[ExceptionUpdateType] = mapped_column(
        Enum(ExceptionUpdateType), nullable=False, index=True,
    )
    source: Mapped[ExceptionUpdateSource] = mapped_column(
        Enum(ExceptionUpdateSource), nullable=False,
    )
    summary: Mapped[str] = mapped_column(
        Text, nullable=False,
        doc="本次 update 的中文摘要 (人/AI 都可写)",
    )
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        doc="原始抓取数据 (LLM 输入/审计用)",
    )
    # AI 元数据
    ai_model: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="v0.6 mock='mock-gpt-4o-mini', 后续接真 LLM",
    )
    ai_confidence: Mapped[float | None] = mapped_column(
        nullable=True, doc="LLM 自评 0-1 置信度 (mock 默认 0.85)",
    )
    # 创建人 (人 / AI / 系统)
    created_by_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ai",  # ai / user / system
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )
    created_by_user_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )

    __table_args__ = (
        Index("ix_exception_updates_org_exception", "organization_id", "exception_id"),
    )

    def __repr__(self) -> str:
        return f"<ExceptionUpdate {self.id} type={self.update_type.value} source={self.source.value}>"


class ExceptionFetchJob(Base, OrganizationScopedMixin, TimestampMixin):
    """后台抓取任务 (AI 跟进的执行单位)

    调度策略 (v0.6.1):
    - 异常创建 → PENDING (立即跑)
    - 每 2h 跑一次 (PENDING 状态)
    - 7 天后自动 CANCELLED (放弃跟进)
    - 单条异常最多 84 次抓取 (7*24/2 = 84)
    """

    __tablename__ = "exception_fetch_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    exception_id: Mapped[str] = mapped_column(
        ForeignKey("operational_exceptions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    status: Mapped[ExceptionFetchJobStatus] = mapped_column(
        Enum(ExceptionFetchJobStatus), default=ExceptionFetchJobStatus.PENDING, nullable=False, index=True,
    )
    source: Mapped[ExceptionUpdateSource] = mapped_column(
        Enum(ExceptionUpdateSource), nullable=False,
    )
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
        doc="下次执行时间 (v0.6.1 用 APScheduler 轮询)",
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    run_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    max_runs: Mapped[int] = mapped_column(
        Integer, default=84, nullable=False,  # 7 天 × 12 次/天
    )

    __table_args__ = (
        Index("ix_exception_fetch_jobs_org_status_next", "organization_id", "status", "next_run_at"),
    )

    def __repr__(self) -> str:
        return f"<ExceptionFetchJob {self.id} ex={self.exception_id[:8]} source={self.source.value} status={self.status.value} run={self.run_count}/{self.max_runs}>"


__all__ = [
    "ExceptionUpdate",
    "ExceptionUpdateType",
    "ExceptionUpdateSource",
    "ExceptionFetchJob",
    "ExceptionFetchJobStatus",
]
