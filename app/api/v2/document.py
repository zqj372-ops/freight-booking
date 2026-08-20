"""Document API - v0.5"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.config import settings
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction
from app.models.document import (
    DOCUMENT_TRANSITIONS,
    Document,
    DocumentExtraction,
    DocumentSource,
    DocumentStatus,
    DocumentType,
    OcrStatus,
    ParseStatus,
)
from app.models.shipment import Shipment
from app.schemas.document import (
    DocumentMatch,
    DocumentRead,
    DocumentStatusTransition,
    ExtractionRead,
)
from app.services.document_service import (
    auto_match_document,
    create_document_from_upload,
    detect_mime_type,
    is_allowed_mime_type,
    run_extraction,
)

router = APIRouter()


@router.post("/upload", response_model=DocumentRead, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    shipment_id: str | None = Form(None),
    doc_type: str = Form("other"),
    db: AsyncSession = Depends(db_session),
) -> DocumentRead:
    """上传文件 (multipart). 自动写本地 + 跑 PDF 文本抽取 + 匹配 Shipment."""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    mime = detect_mime_type(file.filename)
    if not is_allowed_mime_type(mime):
        raise HTTPException(
            status_code=400,
            detail=f"unsupported mime type: {mime} (allowed: pdf, jpeg, png, tiff)",
        )

    # 读 + hash
    content = await file.read()
    if len(content) > settings.upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file too large: {len(content)} bytes (max {settings.upload_size_bytes})",
        )
    from app.services.document_service import compute_file_hash
    file_hash = compute_file_hash(content)

    # 写本地
    today = datetime.now(timezone.utc)
    rel_path = (
        f"attachments/{org.id}/{today.year}/{today.month:02d}/"
        f"{file_hash[:12]}_{file.filename}"
    )
    abs_path = Path(settings.upload_dir) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)

    # 验证 shipment
    if shipment_id:
        s = (await db.execute(
            select(Shipment).where(Shipment.id == shipment_id)
        )).scalar_one_or_none()
        if not s:
            raise HTTPException(status_code=404, detail="shipment not found")

    # 验证 doc_type
    try:
        doc_type_enum = DocumentType(doc_type)
    except ValueError:
        doc_type_enum = DocumentType.OTHER

    # 创建 Document
    doc = await create_document_from_upload(
        db,
        organization_id=org.id,
        filename=file.filename,
        file_path=str(abs_path),
        file_hash=file_hash,
        mime_type=mime,
        file_size=len(content),
        source=DocumentSource.MANUAL_UPLOAD,
        doc_type=doc_type_enum,
        shipment_id=shipment_id,
        uploaded_by=actor.actor_user_id,
        uploaded_by_name=actor.actor_user_name,
    )

    # 跑抽取
    extraction = await run_extraction(db, doc.id, org.id)

    # 自动匹配
    matched_sid, conf = await auto_match_document(db, doc, extraction)
    if matched_sid and not doc.shipment_id:
        doc.shipment_id = matched_sid
        doc.parse_status = ParseStatus.MATCHED_SHIPMENT
        doc.parse_confidence = conf
        await db.commit()
        await db.refresh(doc)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="document",
        entity_id=doc.id,
        action=AuditAction.UPLOAD,
        actor=actor,
        field_changes={
            "filename": doc.filename,
            "file_size": doc.file_size,
            "doc_type": doc_type,
            "extracted_fields": list(extraction.fields.keys()) if extraction else [],
        },
    )
    await db.commit()
    return DocumentRead.model_validate(doc)


@router.get("/", response_model=list[DocumentRead])
async def list_documents(
    shipment_id: str | None = Query(None),
    doc_type: str | None = Query(None),
    ocr_status: str | None = Query(None),
    parse_status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[DocumentRead]:
    org = await get_default_organization(db)
    stmt = select(Document).where(Document.organization_id == org.id)
    if shipment_id:
        stmt = stmt.where(Document.shipment_id == shipment_id)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if ocr_status:
        try:
            ocr_enum = OcrStatus(ocr_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid ocr_status: {ocr_status}")
        stmt = stmt.where(Document.ocr_status == ocr_enum)
    if parse_status:
        try:
            ps_enum = ParseStatus(parse_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid parse_status: {parse_status}")
        stmt = stmt.where(Document.parse_status == ps_enum)
    stmt = stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [DocumentRead.model_validate(r) for r in rows]


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: str, db: AsyncSession = Depends(db_session)
) -> DocumentRead:
    doc = (await db.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="document not found")
    return DocumentRead.model_validate(doc)


@router.get("/{document_id}/extractions", response_model=list[ExtractionRead])
async def list_extractions(
    document_id: str, db: AsyncSession = Depends(db_session)
) -> list[ExtractionRead]:
    stmt = (
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id == document_id)
        .order_by(DocumentExtraction.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [ExtractionRead.model_validate(r) for r in rows]


@router.post("/{document_id}/re-extract", response_model=ExtractionRead)
async def re_extract(
    document_id: str, request: Request, db: AsyncSession = Depends(db_session)
) -> ExtractionRead:
    """重新抽取 (不覆盖, 创建新 DocumentExtraction 记录)"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    doc = (await db.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="document not found")
    extraction = await run_extraction(db, doc.id, org.id)
    if not extraction:
        raise HTTPException(status_code=500, detail="extraction failed")

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="document_extraction",
        entity_id=extraction.id,
        action=AuditAction.OCR_DONE,
        actor=actor,
        field_changes={"after": {"method": extraction.extraction_method.value}},
    )
    await db.commit()
    return ExtractionRead.model_validate(extraction)


@router.post("/{document_id}/match", response_model=DocumentRead)
async def manual_match(
    document_id: str,
    payload: DocumentMatch,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> DocumentRead:
    """手动匹配 document 到 shipment (低置信度时人工指定)"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    doc = (await db.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="document not found")
    s = (await db.execute(
        select(Shipment).where(
            Shipment.id == payload.shipment_id,
            Shipment.organization_id == org.id,
        )
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")

    doc.shipment_id = payload.shipment_id
    doc.parse_status = ParseStatus.MATCHED_SHIPMENT
    doc.parse_confidence = payload.confidence
    await db.commit()
    await db.refresh(doc)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="document",
        entity_id=doc.id,
        action=AuditAction.MATCH,
        actor=actor,
        field_changes={
            "shipment_id": {"old": None, "new": payload.shipment_id},
            "confidence": payload.confidence,
        },
    )
    await db.commit()
    return DocumentRead.model_validate(doc)


# v0.5 1.5.5: Document 文档状态机 transition
@router.post("/{document_id}/transition", response_model=DocumentRead)
async def transition_document(
    document_id: str,
    payload: DocumentStatusTransition,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> DocumentRead:
    """v0.5 1.5.5: 文档状态机 transition

    合法转换 (见 DOCUMENT_TRANSITIONS):
    - pending → uploaded
    - uploaded → matched
    - (any) → archived

    - 写 audit log (action=UPDATE, field_changes={status: {old, new}}, reason 必填)
    - archived 状态自动填 archived_at + archived_by
    - 终态 archived 不能转出
    """
    doc = (await db.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="document not found")
    actor = Actor.from_request(request)

    current_status = (
        doc.status if isinstance(doc.status, DocumentStatus)
        else DocumentStatus(doc.status)
    )
    try:
        target = DocumentStatus(payload.to)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid status: {payload.to}")

    # 验证合法转换
    allowed = DOCUMENT_TRANSITIONS.get(current_status, [])
    if target not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"invalid transition: {current_status.value} → {target.value}. "
                   f"allowed: {[s.value for s in allowed]}",
        )

    old_status = current_status.value
    doc.status = target
    if target == DocumentStatus.ARCHIVED:
        doc.archived_at = datetime.now(timezone.utc)
        doc.archived_by = actor.actor_user_id

    await db.commit()
    await db.refresh(doc)

    await write_audit_log(
        db,
        organization_id=doc.organization_id,
        entity_type="document",
        entity_id=doc.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes={"status": {"old": old_status, "new": target.value}},
        reason=payload.reason,
    )
    await db.commit()
    return DocumentRead.model_validate(doc)
