"""v0.5 Email service - thread 化, 自动匹配"""

from __future__ import annotations

import email
import email.utils
import hashlib
import re
from datetime import datetime, timezone
from email import policy
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email import (
    EmailMessage,
    EmailMessageStatus,
    EmailSource,
    EmailThread,
    EmailThreadStatus,
)
from app.models.shipment import Shipment
from app.services.document_service import extract_job_no_from_subject


def parse_eml_file(file_path: str) -> dict[str, Any]:
    """解析 .eml 文件, 提取关键字段"""
    with open(file_path, "rb") as f:
        raw = f.read()
    msg = email.message_from_bytes(raw, policy=policy.default)

    return {
        "message_id": msg.get("Message-ID", "").strip("<>"),
        "in_reply_to": msg.get("In-Reply-To", "").strip("<>"),
        "references": msg.get("References", ""),
        "from_addr": msg.get("From", ""),
        "to_addrs": [a for a in re.split(r",\s*", msg.get("To", "")) if a],
        "cc_addrs": [a for a in re.split(r",\s*", msg.get("Cc", "")) if a],
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "body_text": _extract_body(msg),
        "attachments": _extract_attachments(msg, file_path),
    }


def _extract_body(msg) -> str:
    """优先 text/plain, 没有就 text/html"""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                return part.get_content()
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return part.get_content()
    else:
        return msg.get_content()
    return ""


def _extract_attachments(msg, source_file: str) -> list[dict[str, str]]:
    """提取附件元信息 (filename + content)"""
    attachments = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            filename = part.get_filename()
            if filename:
                attachments.append({
                    "filename": filename,
                    "content": part.get_payload(decode=True),
                    "content_type": part.get_content_type(),
                })
    return attachments


async def create_email_thread_for_shipment(
    db: AsyncSession,
    *,
    organization_id: str,
    subject: str,
    shipment_id: str | None = None,
    booking_request_id: str | None = None,
    partner_id: str | None = None,
) -> EmailThread:
    """建一个 email thread, 解析主题前缀"""
    subject_prefix = extract_job_no_from_subject(subject)
    thread = EmailThread(
        organization_id=organization_id,
        subject=subject,
        subject_prefix=subject_prefix,
        shipment_id=shipment_id,
        booking_request_id=booking_request_id,
        partner_id=partner_id,
        status=EmailThreadStatus.ACTIVE,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


async def find_or_create_thread_by_in_reply_to(
    db: AsyncSession,
    *,
    organization_id: str,
    subject: str,
    in_reply_to: str | None,
    references: str | None,
    shipment_id: str | None = None,
    partner_id: str | None = None,
) -> EmailThread:
    """按 In-Reply-To 找现有 thread, 找不到按 subject 启发式, 再找不到新建"""
    # 1. 按 In-Reply-To 找
    if in_reply_to:
        # 查 inbound 邮件的 message_id 匹配
        stmt = select(EmailMessage).where(
            EmailMessage.organization_id == organization_id,
            EmailMessage.message_id == in_reply_to.strip("<>"),
        )
        parent = (await db.execute(stmt)).scalar_one_or_none()
        if parent:
            return (await db.execute(
                select(EmailThread).where(EmailThread.id == parent.thread_id)
            )).scalar_one()

    # 2. 按 subject 启发式
    job_no = extract_job_no_from_subject(subject)
    if job_no:
        stmt = select(Shipment).where(
            Shipment.organization_id == organization_id,
            Shipment.job_no == job_no,
        )
        s = (await db.execute(stmt)).scalar_one_or_none()
        if s:
            shipment_id = shipment_id or s.id

    # 3. 找/建 thread
    stmt = select(EmailThread).where(
        EmailThread.organization_id == organization_id,
        EmailThread.shipment_id == shipment_id,
        EmailThread.subject == subject,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing

    return await create_email_thread_for_shipment(
        db,
        organization_id=organization_id,
        subject=subject,
        shipment_id=shipment_id,
        partner_id=partner_id,
    )


async def create_inbound_email_message(
    db: AsyncSession,
    *,
    organization_id: str,
    thread_id: str,
    parsed: dict[str, Any],
    raw_eml_path: str | None = None,
) -> EmailMessage:
    """从 .eml 解析结果创建 inbound EmailMessage"""
    # 解析 date
    received_at = None
    if parsed.get("date"):
        try:
            received_at = email.utils.parsedate_to_datetime(parsed["date"])
        except (TypeError, ValueError):
            received_at = datetime.now(timezone.utc)

    msg = EmailMessage(
        organization_id=organization_id,
        thread_id=thread_id,
        direction="inbound",
        message_id=parsed.get("message_id") or None,
        in_reply_to=parsed.get("in_reply_to") or None,
        references=parsed.get("references") or None,
        from_addr=parsed.get("from_addr", ""),
        to_addrs=parsed.get("to_addrs", []),
        cc_addrs=parsed.get("cc_addrs", []),
        subject=parsed.get("subject", ""),
        body_text=parsed.get("body_text", ""),
        received_at=received_at,
        status=EmailMessageStatus.RECEIVED,
        source=EmailSource.IMAP_POLL,
        raw_eml_path=raw_eml_path,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # 自动匹配 Shipment
    await _try_match_inbound_to_shipment(db, msg, parsed)
    return msg


async def _try_match_inbound_to_shipment(
    db: AsyncSession,
    msg: EmailMessage,
    parsed: dict[str, Any],
) -> None:
    """inbound 邮件自动匹配 Shipment (3 信号策略见 ADR-0003 §11.7)"""
    confidence = 0.0
    matched_shipment_id: str | None = None

    # 信号 1: 主题前缀
    job_no = extract_job_no_from_subject(parsed.get("subject", ""))
    if job_no:
        stmt = select(Shipment).where(
            Shipment.organization_id == msg.organization_id,
            Shipment.job_no == job_no,
        )
        s = (await db.execute(stmt)).scalar_one_or_none()
        if s:
            matched_shipment_id = s.id
            confidence = 0.95

    # 信号 2: In-Reply-To 找到父邮件 → 取父的 shipment
    if not matched_shipment_id and parsed.get("in_reply_to"):
        stmt = select(EmailMessage).where(
            EmailMessage.message_id == parsed["in_reply_to"].strip("<>"),
        )
        parent = (await db.execute(stmt)).scalar_one_or_none()
        if parent and parent.matched_shipment_id:
            matched_shipment_id = parent.matched_shipment_id
            confidence = 0.9

    # 写回
    if matched_shipment_id:
        msg.matched_shipment_id = matched_shipment_id
        msg.match_confidence = confidence
        msg.status = EmailMessageStatus.PROCESSED
        # 更新 thread 的 shipment_id
        thread = (await db.execute(
            select(EmailThread).where(EmailThread.id == msg.thread_id)
        )).scalar_one()
        if not thread.shipment_id:
            thread.shipment_id = matched_shipment_id
        await db.commit()
