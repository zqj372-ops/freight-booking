"""EmailTemplate (邮件模板) 模型"""

import uuid

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._mixins import TimestampMixin


class EmailTemplate(Base, TimestampMixin):
    """订舱邮件 / 通知邮件模板 - Jinja2 渲染"""

    __tablename__ = "email_templates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    # booking_request / booking_confirm / bill_notification / so_received
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)

    def __repr__(self) -> str:
        return f"<EmailTemplate {self.code}>"
