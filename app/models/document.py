"""Document + DocumentExtraction 模型 - v0.5

文件实体. inbound 邮件附件 / outbound 邮件附件 / 手动上传 都是 Document.
DocumentExtraction 单独存 OCR 抽取结果, 与 Document 解耦 (可重新抽取).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin


class DocumentSource(str, enum.Enum):
    """文件来源"""

    IMAP_ATTACHMENT = "imap_attachment"  # IMAP 拉到的邮件附件
    MANUAL_UPLOAD = "manual_upload"  # 手动上传 (UI/CLI)
    GENERATED = "generated"  # 系统生成 (例如 SO 草稿)


class DocumentType(str, enum.Enum):
    """文件类型 (业务分类)"""

    SO = "so"  # Shipping Order
    BL = "bl"  # Bill of Lading 提单
    INVOICE = "invoice"  # 发票
    SI = "si"  # 补料 Shipping Instruction
    VGM = "vgm"  # 重量验证
    PACKING_LIST = "packing_list"  # 装箱单
    OTHER = "other"


class DocumentStatus(str, enum.Enum):
    """v0.5 1.5.5: Document 文档状态机 (4 态)

    pending → uploaded (上传完成) → matched (关联到 Shipment/BC/BR) → archived (业务完结)
    - pending: 刚创建, 还没上传文件 (建 Document 记录但 file_path 占位)
    - uploaded: 文件已落地, 待 OCR / 匹配
    - matched: 已关联到 Shipment/BC/BR, 进入业务流
    - archived: 业务完结, 归档 (不参与匹配, 但保留查询)
    """

    PENDING = "pending"
    UPLOADED = "uploaded"
    MATCHED = "matched"
    ARCHIVED = "archived"


# 合法状态转换图
DOCUMENT_TRANSITIONS: dict[DocumentStatus, list[DocumentStatus]] = {
    DocumentStatus.PENDING: [DocumentStatus.UPLOADED, DocumentStatus.ARCHIVED],
    DocumentStatus.UPLOADED: [DocumentStatus.MATCHED, DocumentStatus.ARCHIVED],
    DocumentStatus.MATCHED: [DocumentStatus.ARCHIVED],
    DocumentStatus.ARCHIVED: [],  # 终态
}


class OcrStatus(str, enum.Enum):
    """OCR 处理状态"""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class ParseStatus(str, enum.Enum):
    """文件 → Shipment 匹配状态"""

    UNMATCHED = "unmatched"
    MATCHED_SHIPMENT = "matched_shipment"
    MATCHED_BOOKING = "matched_booking"
    IGNORED = "ignored"


class ExtractionMethod(str, enum.Enum):
    """抽取方法"""

    REGEX = "regex"
    PDF_TEXT = "pdf_text"
    OCR = "ocr"  # PaddleOCR
    LLM = "llm"  # 留 v0.6
    MANUAL = "manual"


class Document(Base, OrganizationScopedMixin, TimestampMixin):
    """文件, 任何 inbound/outbound/手动上传的文件"""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # 业务关联
    shipment_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
        doc="关联业务单, 可空 (未匹配前)",
    )
    booking_request_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    booking_confirmation_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
        doc="关联到的事实 (如果已被 SO 接受)",
    )

    # 文件元信息
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        doc="SHA256, 用于去重, UNIQUE(organization_id, file_hash)",
    )
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # v0.5 1.5.5: 文档状态机
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.UPLOADED, nullable=False, index=True,
        doc="pending → uploaded → matched → archived",
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="归档时间, status=archived 时填",
    )
    archived_by: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="归档人 user_id",
    )

    # 来源
    source: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource), nullable=False, index=True,
    )
    source_message_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="inbound 邮件附件: 关联 EmailMessage",
    )
    source_account_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="哪个邮箱收到的",
    )

    # 业务分类
    doc_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType), default=DocumentType.OTHER, nullable=False, index=True,
    )
    carrier_hint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, doc="文件名/正文里识别出的船公司",
    )

    # OCR
    ocr_status: Mapped[OcrStatus] = mapped_column(
        Enum(OcrStatus), default=OcrStatus.PENDING, nullable=False, index=True,
    )
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ocr_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 匹配状态
    parse_status: Mapped[ParseStatus] = mapped_column(
        Enum(ParseStatus), default=ParseStatus.UNMATCHED, nullable=False, index=True,
    )
    parse_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    uploaded_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    __table_args__ = (
        # 同组织下 file_hash 唯一 (去重)
        Index("uq_documents_org_file_hash", "organization_id", "file_hash", unique=True),
        Index("ix_documents_org_doc_type", "organization_id", "doc_type"),
    )

    def __repr__(self) -> str:
        return f"<Document {self.filename} {self.doc_type.value} {self.ocr_status.value}>"


class DocumentExtraction(Base, OrganizationScopedMixin, TimestampMixin):
    """OCR/正则/LLM 抽取出的结构化字段, 与 Document 解耦.

    一次抽取 = 一条记录. 重新抽取 = 新增一条, 不覆盖.
    """

    __tablename__ = "document_extractions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    document_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
        doc="FK→documents.id, 阶段 1.3 接入时加 FK constraint",
    )

    # 抽取方法
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        Enum(ExtractionMethod), nullable=False,
    )

    # 抽取结果
    # {field_name: {"value": ..., "confidence": 0.95, "source_bbox": [[x1,y1],[x2,y2]]}}
    fields: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )

    # 与"已接受事实"对比的 diff
    # {field: {"extracted": ..., "expected": ..., "match": bool, "delta_days": int}}
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 审计
    model_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="OCR/LLM 模型版本",
    )
    raw_response: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="模型原始输出 (审计用)",
    )

    __table_args__ = (
        Index("ix_extractions_org_doc", "organization_id", "document_id"),
    )

    def __repr__(self) -> str:
        return f"<DocumentExtraction {self.document_id} {self.extraction_method.value}>"
