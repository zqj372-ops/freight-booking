"""LegacyEntityMap 模型 - v0.4 → v0.5 实体映射

ADR-0005 §3: v0.4 兼容层, 一个 v0.4 实体最多对应一个 v0.5 实体 (一对多则拆 map 记录).
- v04_type: "booking" / "so" / "agent" / "tracking_event" / "email_log" / "bill"
- v05_type: "shipment" / "booking_confirmation" / "document" / "partner" / "milestone" / "email_message" / "skipped"
- v05_id 可空 (例如 v0.4 Bill 在 v0.5 暂未建, v05_type="skipped")
- context: JSON, 存迁移时旧字段值, 用于审计
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin


class LegacyEntityMap(Base, OrganizationScopedMixin, TimestampMixin):
    """v0.4 → v0.5 实体映射表"""

    __tablename__ = "legacy_entity_maps"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    v04_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        doc="booking/so/agent/tracking_event/email_log/bill",
    )
    v04_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
        doc="v0.4 entity UUID",
    )
    v05_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        doc="shipment/booking_confirmation/document/partner/milestone/email_message/bill/skipped",
    )
    v05_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
        doc="v0.5 entity UUID, 可空 (skipped 类型)",
    )
    context: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        doc="迁移时旧字段值 (e.g. v0.4 booking_no)",
    )
    mapped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    __table_args__ = (
        # 1 个 v04 实体可对应 1 个 v05 实体 (e.g. 1 SO → 1 Document + 1 BC)
        Index(
            "uq_legacy_map_v04_v05",
            "organization_id", "v04_type", "v04_id", "v05_type",
            unique=True,
        ),
        Index("ix_legacy_map_v05", "organization_id", "v05_type", "v05_id"),
    )

    def __repr__(self) -> str:
        return f"<LegacyEntityMap {self.v04_type}:{self.v04_id} → {self.v05_type}:{self.v05_id}>"
