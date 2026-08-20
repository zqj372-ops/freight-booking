"""BookingConfirmation (订舱确认) 模型 - v0.5

对方(船公司/代理)发来的 SO/Booking Confirmation.
一个 Shipment 多个版本 (改船期/改港/换船公司/甩柜), is_current 标记当前有效.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
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
    from app.models.booking_request import BookingRequest
    from app.models.document import Document, DocumentExtraction
    from app.models.shipment import Shipment


class BookingConfirmationStatus(str, enum.Enum):
    """BookingConfirmation 状态"""

    UNMATCHED = "unmatched"  # 系统刚拿到, 还没匹配到 Shipment
    MATCHED_PENDING = "matched_pending"  # 已自动匹配候选, 等人工确认
    ACCEPTED = "accepted"  # 人工接受, 字段写入 Shipment
    SUPERSEDED = "superseded"  # 被新版本替代
    REJECTED = "rejected"  # 人工拒绝
    DUPLICATE = "duplicate"  # 与已有版本重复


class BookingConfirmationReviewStatus(str, enum.Enum):
    """审核状态, 与 status 独立"""

    NEEDS_REVIEW = "needs_review"  # OCR 抽取后有低置信度字段
    REVIEWED = "reviewed"  # 全部字段已确认


class BookingConfirmation(Base, OrganizationScopedMixin, TimestampMixin):
    """订舱确认 = 船公司/代理回的事实 (SO/Booking Confirmation 抽取并接受后)"""

    __tablename__ = "booking_confirmations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # 关联
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shipment: Mapped["Shipment"] = relationship("Shipment", lazy="joined")

    booking_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("booking_requests.id", ondelete="SET NULL"),
        nullable=True, index=True,
        doc="可空: 收到的 SO 有时无法立刻匹配到具体某次申请",
    )
    booking_request: Mapped["BookingRequest | None"] = relationship(
        "BookingRequest", lazy="joined",
    )

    # 文档关联
    document_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
        doc="来源 PDF/图片 ID, 阶段 1.3 接入 (FK 关系在 Document model 维护)",
    )
    extraction_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        doc="OCR 抽取结果 ID, 阶段 1.3 接入",
    )

    # 解析得到的字段 (来自 OCR + 人工, 字段来源标注在 extraction 里)
    carrier: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    carrier_booking_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    so_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    bl_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voyage_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pod: Mapped[str | None] = mapped_column(String(64), nullable=True)
    etd: Mapped[date | None] = mapped_column(Date, nullable=True)
    eta: Mapped[date | None] = mapped_column(Date, nullable=True)

    # 截关 (单独存, 不混在 etd/eta 里)
    cy_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    si_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vgm_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cy_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 柜
    container_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    container_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 与申请值的 diff (人工 review 必填)
    context: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        doc='{"diff": {field: {"requested": ..., "confirmed": ..., "match": bool, "delta_days": int}}}',
    )

    # 版本
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True,
        doc="当前有效版本 (一个 Shipment 只有一个 true)",
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("booking_confirmations.id", ondelete="SET NULL"),
        nullable=True,
        doc="旧版指向新版",
    )

    # 状态
    status: Mapped[BookingConfirmationStatus] = mapped_column(
        Enum(BookingConfirmationStatus),
        default=BookingConfirmationStatus.UNMATCHED, nullable=False, index=True,
    )
    review_status: Mapped[BookingConfirmationReviewStatus] = mapped_column(
        Enum(BookingConfirmationReviewStatus),
        default=BookingConfirmationReviewStatus.NEEDS_REVIEW, nullable=False,
    )

    # 接受人
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    accepted_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # 同 Shipment 下 version 唯一
        UniqueConstraint("shipment_id", "version", name="uq_booking_confirmations_shipment_version"),
        Index("ix_booking_confirmations_org_status", "organization_id", "status"),
        Index("ix_booking_confirmations_shipment_current", "shipment_id", "is_current"),
    )

    def __repr__(self) -> str:
        return (
            f"<BookingConfirmation {self.carrier} {self.carrier_booking_no} "
            f"v{self.version} {self.status.value}>"
        )
