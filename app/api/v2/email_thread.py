"""EmailThread + EmailMessage API - v0.5"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction
from app.models.email import EmailMessage, EmailMessageStatus, EmailThread, EmailThreadStatus
from app.models.shipment import Shipment
from app.schemas.email_thread import EmailThreadRead, EmailThreadWithMessages
from app.services.email_service_v5 import (
    create_email_thread_for_shipment,
    create_inbound_email_message,
    find_or_create_thread_by_in_reply_to,
    parse_eml_file,
)

router = APIRouter()


@router.get("/threads", response_model=list[EmailThreadRead])
async def list_threads(
    shipment_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list[EmailThreadRead]:
    org = await get_default_organization(db)
    stmt = select(EmailThread).where(EmailThread.organization_id == org.id)
    if shipment_id:
        stmt = stmt.where(EmailThread.shipment_id == shipment_id)
    if status:
        try:
            s_enum = EmailThreadStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
        stmt = stmt.where(EmailThread.status == s_enum)
    stmt = stmt.order_by(EmailThread.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [EmailThreadRead.model_validate(r) for r in rows]


@router.get("/threads/{thread_id}", response_model=EmailThreadWithMessages)
async def get_thread(
    thread_id: str, db: AsyncSession = Depends(db_session)
) -> EmailThreadWithMessages:
    thread = (await db.execute(
        select(EmailThread).where(EmailThread.id == thread_id)
    )).scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="thread not found")
    msgs = (await db.execute(
        select(EmailMessage)
        .where(EmailMessage.thread_id == thread_id)
        .order_by(EmailMessage.received_at.asc().nulls_first(), EmailMessage.sent_at.asc().nulls_first())
    )).scalars().all()
    from app.schemas.email_thread import EmailMessageRead
    thread_dict = EmailThreadRead.model_validate(thread).model_dump()
    thread_dict["messages"] = [EmailMessageRead.model_validate(m) for m in msgs]
    return EmailThreadWithMessages(**thread_dict)


@router.get("/messages", response_model=list)
async def list_messages(
    thread_id: str | None = Query(None),
    direction: str | None = Query(None),
    status: str | None = Query(None),
    matched_shipment_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(db_session),
) -> list:
    org = await get_default_organization(db)
    stmt = select(EmailMessage).where(EmailMessage.organization_id == org.id)
    if thread_id:
        stmt = stmt.where(EmailMessage.thread_id == thread_id)
    if direction:
        stmt = stmt.where(EmailMessage.direction == direction)
    if status:
        stmt = stmt.where(EmailMessage.status == status)
    if matched_shipment_id:
        stmt = stmt.where(EmailMessage.matched_shipment_id == matched_shipment_id)
    stmt = stmt.order_by(EmailMessage.received_at.desc().nulls_last()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    from app.schemas.email_thread import EmailMessageRead
    return [EmailMessageRead.model_validate(r) for r in rows]


@router.get("/messages/{message_id}", response_model=None)
async def get_message(
    message_id: str, db: AsyncSession = Depends(db_session)
) -> dict:
    msg = (await db.execute(
        select(EmailMessage).where(EmailMessage.id == message_id)
    )).scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="message not found")
    from app.schemas.email_thread import EmailMessageRead
    return EmailMessageRead.model_validate(msg).model_dump()


@router.post("/threads/from-shipment/{shipment_id}", response_model=EmailThreadRead)
async def create_thread_for_shipment(
    shipment_id: str,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> EmailThreadRead:
    """业务详情页点"发邮件"时, 先建/拿一个 thread"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    s = (await db.execute(
        select(Shipment).where(
            Shipment.id == shipment_id,
            Shipment.organization_id == org.id,
        )
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")

    subject = f"[{s.job_no}]"
    thread = await create_email_thread_for_shipment(
        db,
        organization_id=org.id,
        subject=subject,
        shipment_id=shipment_id,
        partner_id=s.current_partner_id,
    )

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="email_thread",
        entity_id=thread.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={"after": {"subject": subject, "shipment_id": shipment_id}},
    )
    await db.commit()
    return EmailThreadRead.model_validate(thread)


@router.post("/ingest-eml", response_model=None)
async def ingest_eml(
    eml_path: str,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> dict:
    """读取 .eml 文件, 创建 inbound EmailMessage + 自动匹配 Shipment.

    v0.5 简化: 不接 IMAP poll, 手动调用此 endpoint 把 .eml 灌进来.
    v0.6 接入 APScheduler 自动定时拉.
    """
    from app.config import settings

    org = await get_default_organization(db)
    actor = Actor.from_request(request)
    path = Path(eml_path)
    if not path.is_absolute():
        path = settings.upload_dir.parent / eml_path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"eml file not found: {eml_path}")

    parsed = parse_eml_file(str(path))

    # 找/建 thread
    thread = await find_or_create_thread_by_in_reply_to(
        db,
        organization_id=org.id,
        subject=parsed.get("subject", ""),
        in_reply_to=parsed.get("in_reply_to"),
        references=parsed.get("references"),
        shipment_id=None,
        partner_id=None,
    )

    # 建 EmailMessage (inbound)
    msg = await create_inbound_email_message(
        db,
        organization_id=org.id,
        thread_id=thread.id,
        parsed=parsed,
        raw_eml_path=str(path),
    )

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="email_message",
        entity_id=msg.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={
            "after": {
                "from": parsed.get("from_addr"),
                "subject": parsed.get("subject"),
                "matched_shipment_id": msg.matched_shipment_id,
            },
        },
    )
    await db.commit()
    return {
        "thread_id": thread.id,
        "message_id": msg.id,
        "matched_shipment_id": msg.matched_shipment_id,
        "match_confidence": msg.match_confidence,
    }
