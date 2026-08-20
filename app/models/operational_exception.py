"""OperationalException (异常) 模型 - v0.5"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.shipment import Shipment


class ExceptionCode(str, enum.Enum):
    BOOKING_RESPONSE_OVERDUE = "booking_response_overdue"  # 订舱申请超过 SLA 未回复
    BOOKING_REJECTED = "booking_rejected"  # 船公司拒接
    SO_MISMATCH = "so_mismatch"  # SO 字段与申请不符
    SCHEDULE_CHANGED = "schedule_changed"  # 船期变更
    PORT_CHANGED = "port_changed"  # 港口变更
    CARRIER_CHANGED = "carrier_changed"  # 船公司变更
    CONTAINER_ROLLED = "container_rolled"  # 甩柜
    CUTOFF_APPROACHING = "cutoff_approaching"  # 截关临近
    CUTOFF_PASSED = "cutoff_passed"  # 截关已过未完成
    SI_OVERDUE = "si_overdue"  # SI 超时未提交
    VGM_OVERDUE = "vgm_overdue"  # VGM 超时未提交
    MISSING_CONTAINER_NO = "missing_container_no"  # 缺柜号
    MISSING_SEAL_NO = "missing_seal_no"  # 缺封条号
    EMAIL_SEND_FAILED = "email_send_failed"  # 邮件发送失败
    EMAIL_PARSE_FAILED = "email_parse_failed"  # 邮件解析失败


class ExceptionSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ExceptionStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    AUTO_CLOSED = "auto_closed"


class ExceptionDetectedBy(str, enum.Enum):
    SYSTEM = "system"  # 系统自动检测
    MANUAL = "manual"  # 操作员手动


class OperationalException(Base, OrganizationScopedMixin, TimestampMixin):
    """业务异常"""

    __tablename__ = "operational_exceptions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shipment: Mapped["Shipment"] = relationship("Shipment", lazy="joined")

    code: Mapped[ExceptionCode] = mapped_column(
        Enum(ExceptionCode), nullable=False, index=True,
    )
    severity: Mapped[ExceptionSeverity] = mapped_column(
        Enum(ExceptionSeverity), default=ExceptionSeverity.WARNING, nullable=False, index=True,
    )
    status: Mapped[ExceptionStatus] = mapped_column(
        Enum(ExceptionStatus), default=ExceptionStatus.OPEN, nullable=False, index=True,
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    detected_by: Mapped[ExceptionDetectedBy] = mapped_column(
        Enum(ExceptionDetectedBy), default=ExceptionDetectedBy.SYSTEM, nullable=False,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolved_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    related_milestone_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )
    related_task_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )

    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_opex_org_shipment", "organization_id", "shipment_id"),
        Index("ix_opex_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<OperationalException {self.code.value} {self.severity.value} {self.status.value}>"
