"""运单跟踪 - 每个 Booking 一组节点"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.booking import Booking


class TrackingStatus(str, enum.Enum):
    """运单状态节点 - 看板 8 列"""

    BOOKED = "booked"  # 已订舱
    EMPTY_PICKED_UP = "empty_picked_up"  # 已提箱
    LOADED = "loaded"  # 已装船
    DEPARTED = "departed"  # 已开船
    IN_TRANSIT = "in_transit"  # 在途
    ARRIVED = "arrived"  # 已到港
    DELIVERED = "delivered"  # 已提货
    COMPLETED = "completed"  # 已完成
    EXCEPTION = "exception"  # 异常


class TrackingSource(str, enum.Enum):
    """节点来源"""

    AUTO = "auto"  # 系统自动 (状态机)
    MANUAL = "manual"  # 操作员手动
    EMAIL = "email"  # 邮件解析
    API = "api"  # 船公司 API


# 状态机的合法推进方向
TRACKING_FLOW: dict[TrackingStatus, list[TrackingStatus]] = {
    TrackingStatus.BOOKED: [TrackingStatus.EMPTY_PICKED_UP, TrackingStatus.EXCEPTION],
    TrackingStatus.EMPTY_PICKED_UP: [TrackingStatus.LOADED, TrackingStatus.EXCEPTION],
    TrackingStatus.LOADED: [TrackingStatus.DEPARTED, TrackingStatus.EXCEPTION],
    TrackingStatus.DEPARTED: [TrackingStatus.IN_TRANSIT, TrackingStatus.ARRIVED, TrackingStatus.EXCEPTION],
    TrackingStatus.IN_TRANSIT: [TrackingStatus.ARRIVED, TrackingStatus.EXCEPTION],
    TrackingStatus.ARRIVED: [TrackingStatus.DELIVERED, TrackingStatus.EXCEPTION],
    TrackingStatus.DELIVERED: [TrackingStatus.COMPLETED, TrackingStatus.EXCEPTION],
    TrackingStatus.COMPLETED: [],
    TrackingStatus.EXCEPTION: [TrackingStatus.IN_TRANSIT, TrackingStatus.DELIVERED, TrackingStatus.COMPLETED],
}


class TrackingEvent(Base, TimestampMixin):
    """运单跟踪事件 / 节点"""

    __tablename__ = "tracking_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    booking_id: Mapped[str] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    booking = relationship("Booking", back_populates="tracking_events", lazy="joined")

    status: Mapped[TrackingStatus] = mapped_column(
        Enum(TrackingStatus), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voyage_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    container_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[TrackingSource] = mapped_column(
        Enum(TrackingSource), default=TrackingSource.MANUAL, nullable=False
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<TrackingEvent {self.booking_id} {self.status} {self.occurred_at}>"
