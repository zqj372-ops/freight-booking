"""Bill (账单) 模型 - 占位, MVP 不实现 OCR 但保留模型"""

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
    OCR_DONE = "ocr_done"
    OCR_FAILED = "ocr_failed"
    CONFIRMED = "confirmed"  # 已对账
    DISPUTED = "disputed"  # 有争议
    PAID = "paid"


class Bill(Base, TimestampMixin):
    """账单 (应收/应付)"""

    __tablename__ = "bills"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    bill_no: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    bill_type: Mapped[str] = mapped_column(String(16), default="receivable")
    # receivable / payable

    # 关联
    booking_id: Mapped[str | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True
    )
    booking = relationship("Booking", lazy="joined")

    # 金额
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 文件
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # OCR 抽取
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # 状态
    status: Mapped[BillStatus] = mapped_column(
        Enum(BillStatus), default=BillStatus.UPLOADED, nullable=False, index=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Bill {self.bill_no} {self.bill_type} {self.total_amount} {self.currency}>"
