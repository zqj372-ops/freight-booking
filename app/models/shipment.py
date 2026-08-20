"""Shipment (业务单, 聚合根) 模型 - v0.5 core workflow"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

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
    from app.models.partner import Partner


class ShipmentStage(str, enum.Enum):
    """Shipment 粗粒度阶段 (v0.5 共 9 个值)

    默认由 Milestone 推导 (见 ADR-0004 §3.1), 不在写操作里硬改.
    UI 提供"手动调整"按钮给特殊场景, 留 audit log + reason 必填.
    """

    DRAFT = "draft"
    BOOKING_IN_PROGRESS = "booking_in_progress"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    BOOKED = "booked"
    CONTAINER_OPERATION = "container_operation"
    DOCUMENTATION = "documentation"
    DEPARTED = "departed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"  # 终态


class Shipment(Base, OrganizationScopedMixin, TimestampMixin):
    """业务单聚合根.

    一个 Shipment = 一个业务单. 客户下单开始, 到开船/账单完成为止.
    9 字段业务编号体系见 ADR-0001 §2.1.
    """

    __tablename__ = "shipments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # ===== 业务编号 (9 字段, 各有含义) =====
    job_no: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        doc="系统内部业务编号, FB-YYYYMMDD-XXXX",
    )
    legacy_job_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        doc="旧 v0.4 Booking.booking_no, 迁移保留",
    )
    customer_ref: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
        doc="客户委托编号",
    )
    customer_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True,
        doc="客户名称 (冗余于 customer_partner.name, 单独保留用于搜索/展示)",
    )
    carrier_booking_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        doc="船公司/代理返回的 Booking Number, 来自 SO 接受后",
    )
    so_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        doc="SO 文件编号, 来自 is_current=true 的 BookingConfirmation",
    )
    bl_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        doc="提单号",
    )

    # ===== 业务阶段 (v0.5 1.5: 8 业务阶段触发字段) =====
    stage: Mapped[ShipmentStage] = mapped_column(
        Enum(ShipmentStage),
        default=ShipmentStage.DRAFT,
        nullable=False,
        index=True,
        doc="默认由 Milestone 推导, 手动调整留 audit log",
    )
    # 触发字段: 17 SLA 任务的时间戳 (Excel "建议新增字段" sheet)
    booking_request_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="订舱申请发送时间, /send 触发",
    )
    so_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="SO 收到时间, 邮件/上传触发 (2h 发拖车行任务)",
    )
    si_info_ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="补料资料齐全时间 (2h 发送 SI 任务)",
    )
    bl_draft_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="提单草稿/修改件收到时间 (30min 核对任务)",
    )
    sealed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="封柜时间 (2h 报关任务)",
    )
    cy_open_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="开港时间 CY Open",
    )
    si_cutoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="补料截止 SI Cut-off",
    )
    vgm_cutoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="VGM 截止",
    )
    cy_cutoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="截港时间 CY Cut-off (报关放行硬截止)",
    )
    empty_return_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="还空柜截止时间 (滞箱超期风险)",
    )
    last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="最后更新时间 (主列表排序, 主管识别未跟进业务)",
    )
    cancellation_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        doc="stage=cancelled 时必填",
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # ===== 客户 =====
    customer_partner_id: Mapped[str | None] = mapped_column(
        ForeignKey("partners.id", ondelete="SET NULL"), nullable=True, index=True,
        doc="FK→partners.id, partner_type=customer",
    )
    customer_partner: Mapped["Partner | None"] = relationship(
        "Partner", foreign_keys=[customer_partner_id], lazy="joined",
    )

    # ===== 路线 =====
    pol: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, doc="Port of Loading (UN/LOCODE 或港口名)",
    )
    pod: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, doc="Port of Discharge",
    )
    final_destination: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="最终目的地 (POD 之后)",
    )
    target_etd: Mapped[date] = mapped_column(
        Date, nullable=False, doc="目标 ETD (操作员录单时填)",
    )
    etd: Mapped[date | None] = mapped_column(
        Date, nullable=True, doc="确认 ETD (来自 is_current BookingConfirmation)",
    )
    eta: Mapped[date | None] = mapped_column(
        Date, nullable=True, doc="确认 ETA",
    )

    # ===== 货物 =====
    commodity: Mapped[str] = mapped_column(
        Text, nullable=False, doc="货物品名",
    )
    hs_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pieces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_cbm: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_dangerous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_oversize: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ===== 柜 (v0.5 强制 1 柜, 字段保留) =====
    container_count: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, doc="v0.5 强制 1, 预留 N",
    )

    # ===== 当前订舱 =====
    current_partner_id: Mapped[str | None] = mapped_column(
        ForeignKey("partners.id", ondelete="SET NULL"), nullable=True, index=True,
        doc="当前在用供应商 (agent_l1/l2/carrier)",
    )
    current_partner: Mapped["Partner | None"] = relationship(
        "Partner", foreign_keys=[current_partner_id], lazy="joined",
    )
    current_carrier: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, doc="当前船公司",
    )

    # ===== 责任 =====
    operator_user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True, doc="FK→users.id, 暂未实现 users 表, 留字段",
    )
    operator_user_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, doc="冗余存操作员名, 方便展示",
    )
    sales_user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="FK→users.id, 销售归属",
    )
    sales_user_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )

    # ===== 报价预留 (v0.5 不实现, 字段留) =====
    rate_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True, doc="报价引用, v0.5 不用",
    )
    rate_valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    commercial_snapshot: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, doc="报价快照 JSON, v0.5 不用",
    )

    # ===== 备注 =====
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # 同组织下 job_no 唯一
        UniqueConstraint("organization_id", "job_no", name="uq_shipments_org_job_no"),
        # 同组织下 legacy_job_no 唯一 (如果有)
        UniqueConstraint(
            "organization_id", "legacy_job_no", name="uq_shipments_org_legacy_job_no"
        ),
        Index("ix_shipments_org_stage", "organization_id", "stage"),
        Index("ix_shipments_org_target_etd", "organization_id", "target_etd"),
    )

    def __repr__(self) -> str:
        return f"<Shipment {self.job_no} {self.pol}->{self.pod} {self.stage.value}>"
