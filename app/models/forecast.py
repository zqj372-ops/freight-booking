"""Forecast (预报单) 模型 - v0.6

v0.6 货量统计的入口表, 解决"周五周六预报集中+数据重复+多源汇总"痛点.
数据源: 物友销售 / 客服 / 深鼎 / 分子公司 (4 源人工 + CSV 导入).
去重: 内容指纹 (customer + pol + pod + target_etd + container_type).

字段尽量少 (操作员周五要录 100+ 预报, 越简单越好). 重量/方数/件数为可选项.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin


class ForecastSource(str, enum.Enum):
    """v0.6 多源预报来源 (按用户描述的 4 个上游)"""

    SALES = "sales"                    # 物友销售
    CUSTOMER_SERVICE = "customer_service"  # 客服
    SHENDING = "shending"              # 深鼎
    SUBSIDIARY = "subsidiary"          # 分子公司
    MANUAL = "manual"                  # 人工补录 (默认)


class ForecastStatus(str, enum.Enum):
    """v0.6 预报状态机"""

    FORECASTED = "forecasted"     # 已预报 (默认)
    CONFIRMED = "confirmed"       # 多源确认 (>=2 源同 content_fingerprint)
    ALLOCATED = "allocated"       # 已配载 (有 shipment_id)
    LOADED = "loaded"             # 已装柜
    CANCELLED = "cancelled"       # 取消


class Forecast(Base, OrganizationScopedMixin, TimestampMixin):
    """预报单 — v0.6 货量统计的基础实体

    一行 = 一个客户的"一票货"的预报.
    多源 dedup 键: content_fingerprint (sha256 of customer + pol + pod + target_etd + container_type).
    """

    __tablename__ = "forecasts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # ===== 来源 (4 源 + manual) =====
    source: Mapped[ForecastSource] = mapped_column(
        Enum(ForecastSource), nullable=False, index=True,
        doc="上游来源: sales/customer_service/shending/subsidiary/manual",
    )
    source_ref: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
        doc="上游系统单号 (dedup 辅助键, 同 (source, source_ref) UNIQUE)",
    )
    content_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        doc="内容指纹 sha256(customer+pol+pod+target_etd+container_type), 跨源 dedup 用",
    )

    # ===== 业务字段 =====
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("partners.id", ondelete="RESTRICT"),
        nullable=False, index=True,
        doc="FK→partners.id, 客户/收货人 (partner_type=customer)",
    )
    customer_name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        doc="冗余 customer.name 便于查询/展示, 不实时 join",
    )
    pol: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        doc="起运港 UN/LOCODE (3-5 字符)",
    )
    pod: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        doc="目的港 UN/LOCODE",
    )
    container_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="40HQ",
        doc="柜型: 20GP/40GP/40HQ/45HQ/20OT/40OT/20FR/40FR",
    )
    container_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    target_etd: Mapped[date] = mapped_column(
        Date, nullable=False, index=True,
        doc="预报的开船日, 决定周汇总归到哪一周",
    )

    # ===== 可选字段 (重货/轻货/危险品) =====
    commodity: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    weight_kg: Mapped[float | None] = mapped_column(
        nullable=True, doc="毛重 KG",
    )
    volume_cbm: Mapped[float | None] = mapped_column(
        nullable=True, doc="体积 CBM",
    )
    pieces: Mapped[int | None] = mapped_column(
        nullable=True, doc="件数",
    )
    is_dangerous: Mapped[bool] = mapped_column(
        default=False, nullable=False, doc="危险品 flag",
    )

    # ===== 状态机 + 配载关联 =====
    status: Mapped[ForecastStatus] = mapped_column(
        Enum(ForecastStatus), default=ForecastStatus.FORECASTED, nullable=False, index=True,
    )
    shipment_id: Mapped[str | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True, index=True,
        doc="配载的 Shipment (allocate 时填, cancel 时清空)",
    )

    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        doc="操作员备注 (例如: 同客户重复预报说明, 异常件标记)",
    )
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        doc="上游导入时的原始数据 (CSV 字段映射, 上游系统 ID 等)",
    )

    # ===== 审计字段 =====
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="录入操作员 (X-User-Id)",
    )
    created_by_user_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, doc="录入操作员姓名 (X-User-Name)",
    )

    __table_args__ = (
        Index("ix_forecasts_org_target_etd", "organization_id", "target_etd"),
        Index("ix_forecasts_org_route", "organization_id", "pol", "pod"),
        Index("ix_forecasts_org_fingerprint", "organization_id", "content_fingerprint"),
        # 跨源 dedup 辅助: 同源同 source_ref 完全去重 (手动 import 上游单号时)
        Index(
            "uq_forecasts_org_source_ref",
            "organization_id", "source", "source_ref",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<Forecast {self.id} {self.customer_name} {self.pol}→{self.pod} {self.container_count}×{self.container_type} etd={self.target_etd} status={self.status.value}>"


__all__ = [
    "Forecast",
    "ForecastSource",
    "ForecastStatus",
]
