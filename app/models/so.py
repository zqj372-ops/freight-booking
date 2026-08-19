"""SO (Shipping Order / 订舱单) 模型"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.booking import Booking


class SOStatus(str, enum.Enum):
    """SO 处理状态"""

    PENDING = "pending"  # 刚收,还没 OCR
    OCR_DONE = "ocr_done"  # OCR 识别完成
    OCR_FAILED = "ocr_failed"  # OCR 识别失败
    CONFIRMED = "confirmed"  # 已确认 (生成 Booking)
    REJECTED = "rejected"  # 拒收


class SO(Base, TimestampMixin):
    """订舱单 (Shipping Order) - 邮件附件 / 上传的 PDF / 图片"""

    __tablename__ = "sos"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # 来源邮件/上传信息
    source: Mapped[str] = mapped_column(String(32), default="upload", index=True)
    # upload / email / api
    source_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 文件信息
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_mime: Mapped[str] = mapped_column(String(128), default="application/pdf")
    file_size: Mapped[int] = mapped_column(default=0)

    # OCR 状态
    status: Mapped[SOStatus] = mapped_column(
        Enum(SOStatus), default=SOStatus.PENDING, nullable=False, index=True
    )
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(nullable=True)
    ocr_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # 抽取的字段 (来自 OCR + 规则解析)
    carrier: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    so_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    bl_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    booking_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voyage_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pol: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    pod: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    etd: Mapped[datetime | None] = mapped_column(nullable=True)
    eta: Mapped[datetime | None] = mapped_column(nullable=True)
    cut_off: Mapped[datetime | None] = mapped_column(nullable=True)
    container_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    container_count: Mapped[int | None] = mapped_column(nullable=True)
    shipper: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consignee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notify_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commodity: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # 关联
    booking_id: Mapped[str | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True
    )
    booking: Mapped["Booking | None"] = relationship(back_populates="so", lazy="joined")

    def __repr__(self) -> str:
        return f"<SO {self.id} {self.carrier} {self.so_number} {self.status}>"
