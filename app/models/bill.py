"""Bill (账单) 模型 - 含 OCR 字段"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import TimestampMixin


class BillStatus(str, enum.Enum):
    UPLOADED = "uploaded"  # 刚上传
    OCR_PROCESSING = "ocr_processing"  # OCR 排队/跑中
    OCR_DONE = "ocr_done"  # OCR + 字段提取完成
    OCR_FAILED = "ocr_failed"
    CONFIRMED = "confirmed"  # 财务确认入账
    DISPUTED = "disputed"  # 有争议
    PAID = "paid"  # 已收/已付


class BillKind(str, enum.Enum):
    """账单类型"""

    VAT_SPECIAL = "vat_special"  # 增值税专用发票
    VAT_NORMAL = "vat_normal"  # 增值税普通发票
    VAT_ELECTRONIC = "vat_electronic"  # 电子发票
    FREIGHT_INVOICE = "freight_invoice"  # 货代发票
    OCEAN_FREIGHT = "ocean_freight"  # 海运费
    DETENTION = "detention"  # 滞箱费
    DEMURRAGE = "demurrage"  # 滞港费
    OTHER = "other"


class Bill(Base, TimestampMixin):
    """账单 (应收/应付)"""

    __tablename__ = "bills"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    bill_no: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    bill_kind: Mapped[BillKind] = mapped_column(
        Enum(BillKind), default=BillKind.OTHER, nullable=False
    )
    bill_type: Mapped[str] = mapped_column(String(16), default="receivable")
    # receivable / payable

    # 关联运单 (一对多) - 来源
    booking_id: Mapped[str | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    booking = relationship("Booking", foreign_keys=[booking_id], lazy="joined")

    # 购销方 (OCR 抽取)
    seller_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_tax_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_tax_no: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 金额
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_excl_tax: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 关联文件
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int] = mapped_column(default=0)

    # OCR 抽取
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    extra_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # 状态
    status: Mapped[BillStatus] = mapped_column(
        Enum(BillStatus), default=BillStatus.UPLOADED, nullable=False, index=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 对账
    matched_booking_id: Mapped[str | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    matched_booking = relationship("Booking", foreign_keys=[matched_booking_id], lazy="joined")
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 0-1, 匹配度 (金额 + 时间 + 票号综合)

    # 回款
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # bank_transfer / alipay / wechat / cash / cheque
    payment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 银行流水号 / 微信交易号

    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Bill {self.bill_no} {self.bill_type} {self.total_amount} {self.currency} {self.status}>"
