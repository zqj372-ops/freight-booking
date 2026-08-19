"""EmailLog (邮件发送记录) 模型"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._mixins import TimestampMixin


class EmailStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RETRYING = "retrying"


class EmailLog(Base, TimestampMixin):
    """邮件发送历史, 用于重试 / 排错"""

    __tablename__ = "email_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    template_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    # 邮件内容
    to_emails: Mapped[list[str]] = mapped_column(JSON, default=list)
    cc_emails: Mapped[list[str]] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[str]] = mapped_column(JSON, default=list)

    # 状态
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus), default=EmailStatus.PENDING, index=True, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0)

    # 关联业务
    booking_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    so_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # 上下文
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    def __repr__(self) -> str:
        return f"<EmailLog {self.id} {self.status} {self.subject[:30]}>"
