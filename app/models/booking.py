"""Booking (订舱) 模型"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.so import SO
    from app.models.agent import Agent
    from app.models.tracking import TrackingEvent


class BookingStatus(str, enum.Enum):
    """订舱状态机"""

    DRAFT = "draft"  # 草稿
    SUBMITTED = "submitted"  # 已发邮件,等船公司回复
    CONFIRMED = "confirmed"  # 船公司确认
    REJECTED = "rejected"  # 船公司拒接
    CANCELLED = "cancelled"  # 操作员取消
    COMPLETED = "completed"  # 已完成


class Booking(Base, TimestampMixin):
    """一份已订舱的订单"""

    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    booking_no: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )

    # 船公司 / 代理
    carrier: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    agent: Mapped["Agent | None"] = relationship(back_populates="bookings", lazy="joined")

    # 航线
    pol: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    pod: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    etd: Mapped[datetime | None] = mapped_column(nullable=True)
    eta: Mapped[datetime | None] = mapped_column(nullable=True)
    cut_off: Mapped[datetime | None] = mapped_column(nullable=True)

    # 货物
    container_type: Mapped[str] = mapped_column(String(16), default="40HQ")
    container_count: Mapped[int] = mapped_column(default=1)
    commodity: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(nullable=True)
    volume_cbm: Mapped[float | None] = mapped_column(nullable=True)

    # 客户
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # 状态
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus),
        default=BookingStatus.DRAFT,
        nullable=False,
        index=True,
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 关联
    so: Mapped["SO | None"] = relationship(back_populates="booking", lazy="selectin")
    tracking_events: Mapped[list["TrackingEvent"]] = relationship(
        back_populates="booking", lazy="selectin", order_by="TrackingEvent.occurred_at"
    )

    def __repr__(self) -> str:
        return f"<Booking {self.booking_no} {self.carrier} {self.pol}->{self.pod} {self.status}>"
