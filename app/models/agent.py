"""Agent (订舱代理) 模型"""

import uuid

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import TimestampMixin


class Agent(Base, TimestampMixin):
    """订舱代理 / 同行 - 用于代订舱/报价"""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    # 联系信息
    contact_person: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_wechat: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 业务信息
    booking_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 接收订舱邮件的地址
    cc_emails: Mapped[list[str]] = mapped_column(JSON, default=list)
    service_routes: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 擅长航线
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    # 关系
    bookings = relationship("Booking", back_populates="agent", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Agent {self.name}>"
