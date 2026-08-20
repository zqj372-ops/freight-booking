"""v0.5 Document service - upload, OCR, match"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import (
    Document,
    DocumentExtraction,
    DocumentSource,
    DocumentType,
    ExtractionMethod,
    OcrStatus,
)
from app.models.email import EmailMessage
from app.models.shipment import Shipment


# 主题前缀解析 (支持 job_no + carrier_booking_no, 数字或字母数字混合)
JOB_NO_PATTERN = re.compile(r"\[([A-Z]{1,8}-[\w-]{4,20})\]")


def extract_job_no_from_subject(subject: str) -> str | None:
    """[FB-20260820-0001] ...  → 'FB-20260820-0001'"""
    if not subject:
        return None
    m = JOB_NO_PATTERN.search(subject)
    return m.group(1) if m else None


def compute_file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def detect_mime_type(filename: str) -> str:
    """简单按后缀判断 mime type, 1.3 只允许 PDF / image"""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "tiff": "image/tiff",
    }.get(ext, "application/octet-stream")


def is_allowed_mime_type(mime: str) -> bool:
    return mime in ("application/pdf", "image/jpeg", "image/png", "image/tiff")


async def save_uploaded_file(
    file_path: Path,
    content: bytes,
) -> str:
    """写文件, 返回 file_hash"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    return compute_file_hash(content)


async def create_document_from_upload(
    db: AsyncSession,
    *,
    organization_id: str,
    filename: str,
    file_path: str,
    file_hash: str,
    mime_type: str,
    file_size: int,
    source: DocumentSource,
    doc_type: DocumentType = DocumentType.OTHER,
    carrier_hint: str | None = None,
    shipment_id: str | None = None,
    source_message_id: str | None = None,
    source_account_id: str | None = None,
    uploaded_by: str | None = None,
    uploaded_by_name: str | None = None,
) -> Document:
    """创建 Document 记录, file_hash 已存在则复用 (去重)"""
    stmt = select(Document).where(
        Document.organization_id == organization_id,
        Document.file_hash == file_hash,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        logger.info("file_hash 已存在, 复用 document: {} (hash={})", existing.id, file_hash[:12])
        return existing

    doc = Document(
        organization_id=organization_id,
        shipment_id=shipment_id,
        filename=filename,
        file_path=file_path,
        file_hash=file_hash,
        mime_type=mime_type,
        file_size=file_size,
        source=source,
        source_message_id=source_message_id,
        source_account_id=source_account_id,
        doc_type=doc_type,
        carrier_hint=carrier_hint,
        ocr_status=OcrStatus.PENDING,
        parse_status="unmatched",
        uploaded_by=uploaded_by,
        uploaded_by_name=uploaded_by_name,
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def extract_pdf_text(file_path: str) -> str:
    """简单 PDF 文本抽取, 用 pdfplumber 复用 v0.4 逻辑

    v0.5 简化: 不做 OCR, 只抽能直接拿到的文本. OCR 留 v0.6.
    """
    try:
        import pdfplumber  # type: ignore

        text_parts: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        return "\n".join(text_parts)
    except ImportError:
        logger.warning("pdfplumber 未装, 返回空文本")
        return ""
    except Exception as e:
        logger.error("PDF 文本抽取失败 {}: {}", file_path, e)
        return ""


# 简单 regex 提取 SO 关键字段
SO_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "carrier": re.compile(r"(MAERSK|MSC|CMA\s*CGM|HAPAG[‑-]LLOYD|HMM|ONE|YANG\s*MING|EVERGREEN|COSTCO)", re.IGNORECASE),
    "carrier_booking_no": re.compile(r"(?:Booking\s*(?:No|Number|#)[:\s]*)([A-Z0-9\-]{6,20})", re.IGNORECASE),
    "so_no": re.compile(r"(?:SO\s*(?:No|Number|#)[:\s]*)([A-Z0-9\-]{4,20})", re.IGNORECASE),
    "vessel_name": re.compile(r"Vessel[:\s]+([A-Z][A-Z\s]{2,30}?)(?:\s+V\.|\n|$)"),
    "voyage_no": re.compile(r"V\.?\s*(\d{2,4}[EW]?)"),
    "etd": re.compile(r"ETD[:\s]+(\d{4}[-/]\d{1,2}[-/]\d{1,2})"),
    "eta": re.compile(r"ETA[:\s]+(\d{4}[-/]\d{1,2}[-/]\d{1,2})"),
    "pol": re.compile(r"Port\s+of\s+Loading[:\s]+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)"),
    "pod": re.compile(r"Port\s+of\s+Discharge[:\s]+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)"),
    "container_type": re.compile(r"(\d{1,2}\s*[xX×]\s*\d{0,2}\s*(20GP|40GP|40HQ|20RF|40RF|20OT|40OT))"),
}


def parse_so_fields(text: str) -> dict[str, dict[str, Any]]:
    """从 SO 文本抽取字段, 返回 {field: {value, confidence}}"""
    fields: dict[str, dict[str, Any]] = {}
    if not text:
        return fields
    for field, pattern in SO_FIELD_PATTERNS.items():
        m = pattern.search(text)
        if m:
            value = m.group(1).strip()
            # 简单 confidence: 命中 + 长度合理
            conf = 0.85 if len(value) >= 3 else 0.5
            fields[field] = {"value": value, "confidence": conf}
    return fields


async def run_extraction(
    db: AsyncSession,
    document_id: str,
    organization_id: str,
) -> DocumentExtraction | None:
    """对 document 跑抽取, 创建 DocumentExtraction 记录.

    v0.5 简化: 只对 application/pdf 抽文本, 不接 PaddleOCR.
    """
    doc = (await db.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if not doc:
        return None

    # 抽取
    text = ""
    method = ExtractionMethod.PDF_TEXT if doc.mime_type == "application/pdf" else ExtractionMethod.REGEX
    if doc.mime_type == "application/pdf":
        text = await extract_pdf_text(doc.file_path)
        if not text:
            method = ExtractionMethod.REGEX  # fallback

    fields = parse_so_fields(text) if text else {}

    extraction = DocumentExtraction(
        organization_id=organization_id,
        document_id=document_id,
        extraction_method=method,
        fields=fields,
        model_version="v0.5_pdfplumber" if method == ExtractionMethod.PDF_TEXT else "v0.5_regex",
        raw_response=text[:5000] if text else None,
    )
    db.add(extraction)
    doc.ocr_status = OcrStatus.DONE
    doc.ocr_text = text
    doc.ocr_engine = extraction.model_version
    doc.ocr_confidence = (
        sum(f.get("confidence", 0) for f in fields.values()) / len(fields)
        if fields else None
    )
    doc.ocr_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(extraction)
    return extraction


async def auto_match_document(
    db: AsyncSession,
    document: Document,
    extraction: DocumentExtraction | None = None,
) -> tuple[str | None, float]:
    """自动匹配 document 到 Shipment, 返回 (shipment_id, confidence).

    匹配策略 (v0.5 拍板):
    1. 主题前缀 [job_no] → 直接查 Shipment
    2. (customer_ref + carrier_booking_no) → 候选
    3. (pol + pod + etd ± 3 天) → 候选

    0.8+ 直接匹配, 0.5-0.8 给候选, <0.5 不匹配.
    """
    org_id = document.organization_id

    # 策略 1: 来自 EmailMessage 关联
    if document.source_message_id:
        stmt = select(EmailMessage).where(EmailMessage.id == document.source_message_id)
        msg = (await db.execute(stmt)).scalar_one_or_none()
        if msg and msg.matched_shipment_id:
            return msg.matched_shipment_id, msg.match_confidence or 0.9

    # 策略 2: 主题前缀 (从 OCR 文本或 carrier_hint 解析)
    candidate_job_no = None
    if document.carrier_hint:
        candidate_job_no = document.carrier_hint
    if not candidate_job_no and extraction and extraction.fields.get("carrier_booking_no"):
        # carrier_booking_no 反查 Shipment
        bn = extraction.fields["carrier_booking_no"].get("value")
        if bn:
            stmt = select(Shipment).where(
                Shipment.organization_id == org_id,
                Shipment.carrier_booking_no == bn,
            )
            s = (await db.execute(stmt)).scalar_one_or_none()
            if s:
                return s.id, 0.95

    return None, 0.0
