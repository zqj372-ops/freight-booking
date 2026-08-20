"""Document + DocumentExtraction schemas - v0.5"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DocumentSourceLiteral = Literal["imap_attachment", "manual_upload", "generated"]
DocumentTypeLiteral = Literal["so", "bl", "invoice", "si", "vgm", "packing_list", "other"]
DocumentStatusLiteral = Literal["pending", "uploaded", "matched", "archived"]
OcrStatusLiteral = Literal["pending", "processing", "done", "failed"]
ParseStatusLiteral = Literal["unmatched", "matched_shipment", "matched_booking", "ignored"]
ExtractionMethodLiteral = Literal["regex", "pdf_text", "ocr", "llm", "manual"]


class DocumentUpload(BaseModel):
    """手动上传文件 (multipart form), 或通过 JSON + file_path (内部调用)"""

    shipment_id: str | None = None
    doc_type: DocumentTypeLiteral = "other"
    carrier_hint: str | None = None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    shipment_id: str | None
    booking_request_id: str | None
    booking_confirmation_id: str | None
    filename: str
    file_path: str
    file_hash: str
    mime_type: str
    file_size: int
    source: str
    source_message_id: str | None
    source_account_id: str | None
    doc_type: str
    carrier_hint: str | None
    ocr_status: str
    ocr_text: str | None
    ocr_engine: str | None
    ocr_confidence: float | None
    ocr_at: datetime | None
    ocr_error: str | None
    parse_status: str
    parse_confidence: float | None
    uploaded_by: str | None
    uploaded_by_name: str | None
    uploaded_at: datetime
    # v0.5 1.5.5: 文档状态机
    status: str
    archived_at: datetime | None
    archived_by: str | None
    created_at: datetime
    updated_at: datetime


class DocumentMatch(BaseModel):
    """手动匹配 document 到 shipment"""

    shipment_id: str
    confidence: float = Field(1.0, ge=0, le=1)


class DocumentStatusTransition(BaseModel):
    """v0.5 1.5.5: 文档状态机 transition

    合法转换:
    - pending → uploaded
    - uploaded → matched
    - (any) → archived
    reason 必填 (>= 5 字符)
    """

    to: DocumentStatusLiteral
    reason: str = Field(..., min_length=5, description="转换原因")


class ExtractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    document_id: str
    extraction_method: str
    fields: dict[str, Any]
    diff: dict[str, Any] | None
    model_version: str | None
    raw_response: str | None
    created_at: datetime
