"""EmailThread + EmailMessage 模型 - v0.5

邮件线程 (聚合一组 inbound + outbound 邮件).
单封邮件, 区分 inbound (IMAP 拉) / outbound (SMTP 发).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin


class EmailThreadStatus(str, enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    SPAM = "spam"


class EmailDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class EmailMessageStatus(str, enum.Enum):
    """邮件状态"""

    DRAFT = "draft"  # outbound 草稿
    QUEUED = "queued"  # outbound 排队发送
    SENT = "sent"  # outbound 已发送
    FAILED = "failed"  # outbound 失败
    RECEIVED = "received"  # inbound 收到
    PROCESSING = "processing"  # inbound 解析中
    PROCESSED = "processed"  # inbound 处理完
    IGNORED = "ignored"  # inbound 忽略 (垃圾/未匹配)


class EmailSource(str, enum.Enum):
    SMTP_SEND = "smtp_send"
    IMAP_POLL = "imap_poll"
    MANUAL = "manual"  # 手动上传 .eml


class EmailThread(Base, OrganizationScopedMixin, TimestampMixin):
    """邮件线程, 聚合 inbound + outbound"""

    __tablename__ = "email_threads"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # 主题
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    subject_prefix: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        doc="解析出的 [FB-20260820-0001] 前缀",
    )

    # 业务关联 (v0.5 至少 1 个)
    shipment_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    booking_request_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    partner_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
        doc="对方 (船公司/代理/客户)",
    )

    status: Mapped[EmailThreadStatus] = mapped_column(
        Enum(EmailThreadStatus), default=EmailThreadStatus.ACTIVE, nullable=False, index=True,
    )

    __table_args__ = (
        Index("ix_email_threads_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<EmailThread {self.subject[:30]}>"


class EmailMessage(Base, OrganizationScopedMixin, TimestampMixin):
    """单封邮件, inbound / outbound"""

    __tablename__ = "email_messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    thread_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
        doc="FK→email_threads.id",
    )

    direction: Mapped[EmailDirection] = mapped_column(
        Enum(EmailDirection), nullable=False, index=True,
    )

    # RFC 5322 字段
    message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True,
        doc="RFC 5322 Message-ID, inbound 必填, outbound 可空",
    )
    in_reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    references: Mapped[str | None] = mapped_column(Text, nullable=True)

    from_addr: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    to_addrs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    cc_addrs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[EmailMessageStatus] = mapped_column(
        Enum(EmailMessageStatus), default=EmailMessageStatus.DRAFT, nullable=False, index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)

    source: Mapped[EmailSource] = mapped_column(
        Enum(EmailSource), nullable=False, default=EmailSource.MANUAL,
    )
    raw_eml_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, doc="原始 .eml 文件路径 (IMAP)",
    )

    # 自动匹配 (inbound 才有)
    matched_shipment_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    matched_booking_request_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )
    match_confidence: Mapped[float | None] = mapped_column(default=None, nullable=True)

    __table_args__ = (
        Index("ix_email_messages_org_status", "organization_id", "status"),
        Index("ix_email_messages_thread", "thread_id"),
    )

    def __repr__(self) -> str:
        return f"<EmailMessage {self.direction.value} {self.subject[:30]}>"
