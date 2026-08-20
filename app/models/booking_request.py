"""BookingRequest (订舱申请) 模型 - v0.5

我发出, 对方(船公司/代理)回 SO 确认.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.partner import Partner
    from app.models.shipment import Shipment


class BookingRequestStatus(str, enum.Enum):
    """BookingRequest 状态机 (v0.5)"""

    DRAFT = "draft"
    SENT = "sent"  # 邮件已发出
    ACKNOWLEDGED = "acknowledged"  # 供应商回邮说收到
    CONFIRMED = "confirmed"  # 供应商回 SO/Booking
    REJECTED = "rejected"  # 供应商拒
    CANCELLED = "cancelled"  # 我方取消, 终态


class BookingRequest(Base, OrganizationScopedMixin, TimestampMixin):
    """订舱申请, 每次对外发订舱创建一条.

    改 ETD/改港/换船公司 → 必创建新版本 (递增 request_version, supersedes_id 链接).
    """

    __tablename__ = "booking_requests"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # 关联
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shipment: Mapped["Shipment"] = relationship("Shipment", lazy="joined")

    partner_id: Mapped[str] = mapped_column(
        ForeignKey("partners.id", ondelete="RESTRICT"),
        nullable=False, index=True,
        doc="供应商 (agent_l1/agent_l2/carrier)",
    )
    partner: Mapped["Partner"] = relationship("Partner", lazy="joined")

    # 编号
    booking_request_no: Mapped[str] = mapped_column(
        String(32), nullable=False,
        doc="BR-001/BR-002 系统生成, Shipment 内递增",
    )
    request_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, doc="1, 2, 3 ...",
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("booking_requests.id", ondelete="SET NULL"),
        nullable=True,
        doc="旧版指向新版 (业务时间序)",
    )

    # 申请时的快照 (cargo_snapshot): 当时锁定的客户/货物/路线/柜型
    cargo_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
        doc="申请时刻的 shipment 字段快照, 防止 Shipment 改了之后找不到原值",
    )
    requested_etd: Mapped[date] = mapped_column(Date, nullable=False)
    requested_pol: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_pod: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_container_type: Mapped[str] = mapped_column(
        String(16), default="40HQ", nullable=False,
    )
    requested_container_count: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False,
    )
    carrier_preference: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="船公司偏好, 写入 cargo_snapshot 不够灵活, 单独存",
    )

    # 邮件上下文 (发出去后填)
    email_thread_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="FK→email_threads.id, 阶段 1.3 接入",
    )
    email_message_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="FK→email_messages.id",
    )
    email_account_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="FK→email_accounts.id, v0.5 暂不实现多账号",
    )

    # 状态
    status: Mapped[BookingRequestStatus] = mapped_column(
        Enum(BookingRequestStatus),
        default=BookingRequestStatus.DRAFT, nullable=False, index=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SLA
    expected_response_by: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="操作员填的 SLA 截止时间",
    )
    response_sla_hours: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="默认 24h, 来自 partner.response_sla_hours",
    )

    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # 同 Shipment 下 booking_request_no 唯一
        UniqueConstraint(
            "shipment_id", "booking_request_no", name="uq_booking_requests_shipment_no"
        ),
        Index("ix_booking_requests_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<BookingRequest {self.booking_request_no} v{self.request_version} {self.status.value}>"
