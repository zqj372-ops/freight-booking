"""Email Ingestion 模型 - IMAP 拉取会话 + 去重记录"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import TimestampMixin


class IngestionStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class IngestionSource(str, enum.Enum):
    IMAP = "imap"  # 真实邮箱
    MOCK = "mock"  # 本地 .eml 样本
    MANUAL = "manual"  # 手动上传


class EmailIngestion(Base, TimestampMixin):
    """一次 IMAP 拉取会话"""

    __tablename__ = "email_ingestions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source: Mapped[IngestionSource] = mapped_column(
        Enum(IngestionSource), default=IngestionSource.IMAP, nullable=False
    )
    mailbox: Mapped[str] = mapped_column(String(64), default="INBOX")

    status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus), default=IngestionStatus.RUNNING, nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 统计
    total_fetched: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    skip_count: Mapped[int] = mapped_column(Integer, default=0)  # 已处理/过滤掉
    error_count: Mapped[int] = mapped_column(Integer, default=0)

    # 错误信息
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 关联 SO 列表 (JSON 数组存 ID)
    so_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    skipped_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    def __repr__(self) -> str:
        return f"<EmailIngestion {self.id} {self.source} {self.status} new={self.new_count}>"


class ProcessedEmail(Base):
    """已处理的邮件 - 用于去重 (按 message_id 哈希)"""

    __tablename__ = "processed_emails"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # IMAP Message-ID 或附件 SHA256
    message_id_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # 32 字节 SHA256 hex

    # 元信息
    from_addr: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[IngestionSource] = mapped_column(
        Enum(IngestionSource), default=IngestionSource.IMAP, nullable=False
    )

    # 关联 SO
    so_id: Mapped[str | None] = mapped_column(
        ForeignKey("sos.id", ondelete="SET NULL"), nullable=True
    )
    so = relationship("SO", lazy="joined")

    # 处理时间
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_id: Mapped[str | None] = mapped_column(
        ForeignKey("email_ingestions.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_processed_emails_received", "received_at"),
    )

    def __repr__(self) -> str:
        return f"<ProcessedEmail {self.message_id_hash[:12]}>"
