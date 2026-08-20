"""v0.5 Bill model - 扩展 v0.4 字段 (加 shipment_id, payment_proof_status, 状态机)

设计:
- 独立表 bills_v5 (不与 v0.4 bills 冲突, v0.4 表继续用于兼容 /api/v1)
- 关联 v0.5 Shipment (替代 v0.4 booking_id)
- 7 状态: UPLOADED / OCR_PROCESSING / OCR_DONE / OCR_FAILED / CONFIRMED / DISPUTED / PAID
  合法转换见 BILL_TRANSITIONS
- payment_proof_status: 5 态 (not_provided/provided/confirmed/...) v0.5 1.5 复用
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.shipment import Shipment


class BillType(str, enum.Enum):
    """账单类型 (应收/应付)"""

    RECEIVABLE = "receivable"  # 应收 (客户付我们)
    PAYABLE = "payable"  # 应付 (我们付供应商/船公司)


class BillStatus(str, enum.Enum):
    """账单状态机 (7 态)"""

    UPLOADED = "uploaded"  # 刚上传, 待 OCR
    OCR_PROCESSING = "ocr_processing"  # OCR 排队/跑中
    OCR_DONE = "ocr_done"  # OCR + 字段提取完成
    OCR_FAILED = "ocr_failed"  # OCR 失败
    CONFIRMED = "confirmed"  # 财务确认入账
    DISPUTED = "disputed"  # 有争议
    PAID = "paid"  # 已收/已付


class BillKind(str, enum.Enum):
    """账单种类 (税票类型)"""

    VAT_SPECIAL = "vat_special"
    VAT_NORMAL = "vat_normal"
    VAT_ELECTRONIC = "vat_electronic"
    FREIGHT_INVOICE = "freight_invoice"
    OCEAN_FREIGHT = "ocean_freight"
    DETENTION = "detention"
    DEMURRAGE = "demurrage"
    OTHER = "other"


# 状态机转换图
BILL_TRANSITIONS: dict[BillStatus, list[BillStatus]] = {
    BillStatus.UPLOADED: [BillStatus.OCR_PROCESSING, BillStatus.OCR_FAILED, BillStatus.CONFIRMED],
    BillStatus.OCR_PROCESSING: [BillStatus.OCR_DONE, BillStatus.OCR_FAILED],
    BillStatus.OCR_DONE: [BillStatus.CONFIRMED, BillStatus.DISPUTED, BillStatus.OCR_PROCESSING],
    BillStatus.OCR_FAILED: [BillStatus.OCR_PROCESSING, BillStatus.UPLOADED],
    BillStatus.CONFIRMED: [BillStatus.PAID, BillStatus.DISPUTED],
    BillStatus.DISPUTED: [BillStatus.CONFIRMED, BillStatus.PAID],
    BillStatus.PAID: [],  # 终态
}


class BillV5(Base, OrganizationScopedMixin, TimestampMixin):
    """v0.5 账单 - 扩展 v0.4 字段"""

    __tablename__ = "bills_v5"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # 业务编号
    bill_no: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    # 类型
    bill_type: Mapped[BillType] = mapped_column(
        Enum(BillType), default=BillType.RECEIVABLE, nullable=False, index=True
    )
    bill_kind: Mapped[BillKind] = mapped_column(
        Enum(BillKind), default=BillKind.OTHER, nullable=False
    )

    # 业务关联 (v0.5 新: shipment_id 替代 v0.4 booking_id)
    shipment_id: Mapped[str | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    shipment = relationship("Shipment", foreign_keys=[shipment_id], lazy="joined")
    matched_shipment_id: Mapped[str | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True, index=True,
        doc="系统/财务匹配后的 shipment",
    )
    matched_shipment = relationship("Shipment", foreign_keys=[matched_shipment_id], lazy="joined")

    # 购销方 (OCR 抽取或手工)
    seller_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_tax_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_tax_no: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 金额
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_excl_tax: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 文件
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # OCR
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    extra_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # 状态
    status: Mapped[BillStatus] = mapped_column(
        Enum(BillStatus), default=BillStatus.UPLOADED, nullable=False, index=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 匹配
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    match_score: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        doc="0-1, 金额 + 时间 + 票号综合匹配度",
    )

    # 回款
    payment_method: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        doc="bank_transfer/alipay/wechat/cash/cheque",
    )
    payment_ref: Mapped[str | None] = mapped_column(
        String(128), nullable=True, doc="银行流水号 / 微信交易号",
    )
    payment_proof_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        doc="not_provided/provided/confirmed (v0.5 1.5 复用)",
    )
    payment_proof_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    payment_proof_uploaded_by: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )

    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_bills_v5_org_status", "organization_id", "status"),
        Index("ix_bills_v5_org_due", "organization_id", "due_at"),
    )

    def __repr__(self) -> str:
        return f"<BillV5 {self.bill_no} {self.bill_type.value} {self.total_amount} {self.currency} {self.status.value}>"
