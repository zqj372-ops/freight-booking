"""v0.6.3 头程时效 数据模型

- EtaUpdate: ETA 变更历史 (每次 ETA 改一次记一行, 含 change_reason / source)
- 复用 v0.5 Shipment.eta + Document 提取, 不新建 ETA 主表 (用 v0.5 已有)
- v0.6.3 新增 3 个 ExceptionCode (ETA_DELAYED / ETA_PASSED_UNLOADED / ETA_PASSED_DELIVERED)
  + 1 个 TriggerEvent (ETA_DELAYS_DETECTED)
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin


class EtaUpdateSource(str, enum.Enum):
    """ETA 变更来源"""

    MANUAL = "manual"                # 操作员 PATCH Shipment.eta
    DOCUMENT = "document"            # DocumentExtraction 提单/船期表提取
    CARRIER_API = "carrier_api"      # 船公司 API (v0.6.1 mock)
    SYSTEM = "system"                # 系统自动 (延误检测后建议)


class EtaUpdateReason(str, enum.Enum):
    """ETA 变更原因"""

    INITIAL = "initial"              # 首次设定
    CARRIER_REVISE = "carrier_revise"  # 船公司主动修订
    PORT_DELAY = "port_delay"        # 港口拥堵延误
    WEATHER = "weather"              # 天气原因
    VESSEL_DELAY = "vessel_delay"    # 船期延误
    DOCUMENTATION = "documentation"  # 文件延迟
    ROLLED = "rolled"                # 甩柜/漏装
    OTHER = "other"


class EtaUpdate(Base, OrganizationScopedMixin, TimestampMixin):
    """ETA 变更历史 (Shipment 每次 eta 改一次记一行, 用于追溯延误来源)"""

    __tablename__ = "eta_updates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    old_eta: Mapped[date | None] = mapped_column(
        Date, nullable=True, doc="原 ETA (首次记 None)",
    )
    new_eta: Mapped[date] = mapped_column(
        Date, nullable=False, doc="新 ETA",
    )
    delta_days: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        doc="差值天数 (new_eta - old_eta), 首次为 0",
    )
    source: Mapped[EtaUpdateSource] = mapped_column(
        Enum(EtaUpdateSource), nullable=False, index=True,
    )
    reason: Mapped[EtaUpdateReason] = mapped_column(
        Enum(EtaUpdateReason), default=EtaUpdateReason.OTHER, nullable=False,
    )
    change_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="详细说明 (e.g. 客户说船公司邮件通知延期 3 天)",
    )
    related_document_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        doc="如果是 Document 提取, 关联 doc",
    )
    # 操作员 (人工修改时)
    updated_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by_user_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 是否自动建了 OperationalException
    triggered_exception_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )

    __table_args__ = (
        Index("ix_eta_updates_org_shipment", "organization_id", "shipment_id"),
        Index("ix_eta_updates_shipment_created", "shipment_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<EtaUpdate ship={self.shipment_id[:8]} {self.old_eta}->{self.new_eta} ({self.delta_days:+d}d) source={self.source.value}>"


__all__ = [
    "EtaUpdate",
    "EtaUpdateSource",
    "EtaUpdateReason",
]
