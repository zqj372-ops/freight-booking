"""Milestone (业务节点) 模型 - v0.5

不可变日志, 一旦记录只能 corrected_at 标记, 不能改字段.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.shipment import Shipment


class MilestoneCode(str, enum.Enum):
    """Milestone.code 枚举 (动词过去式_名词)"""

    BOOKING_REQUEST_SENT = "booking_request_sent"
    BOOKING_REQUEST_ACKNOWLEDGED = "booking_request_acknowledged"
    BOOKING_CONFIRMATION_RECEIVED = "booking_confirmation_received"
    BOOKING_CONFIRMATION_ACCEPTED = "booking_confirmation_accepted"
    BOOKING_REJECTED = "booking_rejected"
    EMPTY_RELEASE_AVAILABLE = "empty_release_available"
    CONTAINER_PICKED_UP = "container_picked_up"
    CONTAINER_GATED_IN = "container_gated_in"
    CONTAINER_LOADED = "container_loaded"
    SI_SUBMITTED = "si_submitted"
    VGM_SUBMITTED = "vgm_submitted"
    CUSTOMS_CLEARED = "customs_cleared"
    SI_CUTOFF_PASSED = "si_cutoff_passed"
    VGM_CUTOFF_PASSED = "vgm_cutoff_passed"
    CY_CUTOFF_PASSED = "cy_cutoff_passed"
    GATE_IN = "gate_in"
    DEPARTED = "departed"
    ARRIVED_AT_POL = "arrived_at_pol"
    IN_TRANSIT = "in_transit"
    ARRIVED_AT_POD = "arrived_at_pod"
    CUSTOMS_CLEARED_AT_POD = "customs_cleared_at_pod"
    CONTAINER_DISCHARGED = "container_discharged"
    DELIVERED = "delivered"
    EMPTY_RETURNED = "empty_returned"


class MilestoneSource(str, enum.Enum):
    """Milestone 来源"""

    AUTO = "auto"  # 系统自动 (例如 BC accept)
    MANUAL = "manual"  # 操作员手动
    EMAIL = "email"  # 邮件解析
    API = "api"  # 船公司 API


class Milestone(Base, OrganizationScopedMixin, TimestampMixin):
    """业务节点, 不可变日志"""

    __tablename__ = "milestones"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shipment: Mapped["Shipment"] = relationship("Shipment", lazy="joined")

    code: Mapped[MilestoneCode] = mapped_column(
        Enum(MilestoneCode), nullable=False, index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        doc="业务发生时间 (用户填/系统推测)",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        doc="系统记录时间 (created_at 的 alias)",
    )

    source: Mapped[MilestoneSource] = mapped_column(
        Enum(MilestoneSource), default=MilestoneSource.MANUAL, nullable=False,
    )
    source_ref: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        doc="邮件 Message-ID / API 调用 ID 等",
    )

    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voyage_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    container_no: Mapped[str | None] = mapped_column(String(32), nullable=True)

    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 修正
    corrected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    corrected_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    corrected_milestone_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        doc="指向修正后的新 Milestone (如果有)",
    )

    __table_args__ = (
        Index("ix_milestones_org_shipment", "organization_id", "shipment_id"),
        Index("ix_milestones_shipment_occurred", "shipment_id", "occurred_at"),
    )

    def __repr__(self) -> str:
        return f"<Milestone {self.code.value} {self.occurred_at}>"
