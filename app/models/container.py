"""Container (柜) 模型 - v0.5

v0.5 强制 1 个 Shipment = 1 个柜, 业务上 container_count=1 即可.
但 Container 是独立表 (子表), 阶段 1.4 / 1.3 录入柜号/封条号用.
v0.6+ 多柜展开, 此表已经是 N 个.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.shipment import Shipment


class ContainerStatus(str, enum.Enum):
    """Container 状态"""

    PENDING = "pending"  # 待提柜
    PICKED_UP = "picked_up"  # 已提柜
    LOADED = "loaded"  # 已装船
    IN_TRANSIT = "in_transit"
    DISCHARGED = "discharged"  # 已卸船
    RETURNED = "returned"  # 已还箱


class Container(Base, OrganizationScopedMixin, TimestampMixin):
    """柜, v0.5 一个 Shipment 默认 1 个 Container"""

    __tablename__ = "containers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shipment: Mapped["Shipment"] = relationship("Shipment", lazy="joined")

    # 柜标识
    container_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True,
        doc="柜号 (船公司分配或提柜时录入), 例 'MSKU1234567'",
    )
    seal_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, doc="封条号",
    )
    container_type: Mapped[str] = mapped_column(
        String(16), default="40HQ", nullable=False,
    )

    # 现场数据
    pickup_location: Mapped[str | None] = mapped_column(String(255), nullable=True, doc="提柜地点")
    pickup_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    loaded_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 件重尺
    pieces: Mapped[int | None] = mapped_column(nullable=True)
    gross_weight_kg: Mapped[float | None] = mapped_column(nullable=True)
    volume_cbm: Mapped[float | None] = mapped_column(nullable=True)

    status: Mapped[ContainerStatus] = mapped_column(
        Enum(ContainerStatus),
        default=ContainerStatus.PENDING, nullable=False, index=True,
    )

    __table_args__ = (
        Index("ix_containers_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Container {self.container_no or '(未提)'} {self.container_type} {self.status.value}>"
