"""邮件服务 - SMTP 发送 + 模板渲染 + 重试"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any

from jinja2 import Template
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email_log import EmailLog, EmailStatus


@dataclass
class EmailMessage:
    to_emails: list[str]
    cc_emails: list[str]
    subject: str
    body: str  # HTML or plain text
    attachments: list[str]
    is_html: bool = True
    template_code: str | None = None
    booking_id: str | None = None
    so_id: str | None = None
    context: dict[str, Any] | None = None


def render_template(subject_tpl: str, body_tpl: str, context: dict[str, Any]) -> tuple[str, str]:
    """用 Jinja2 渲染邮件主题和正文"""
    s = Template(subject_tpl).render(**context)
    b = Template(body_tpl).render(**context)
    return s, b


def build_mime(msg: EmailMessage) -> MIMEMultipart:
    mime = MIMEMultipart("alternative" if not msg.attachments else "mixed")
    mime["Subject"] = msg.subject
    mime["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
    mime["To"] = ", ".join(msg.to_emails)
    if msg.cc_emails:
        mime["Cc"] = ", ".join(msg.cc_emails)

    if msg.is_html:
        mime.attach(MIMEText(msg.body, "html", "utf-8"))
    else:
        mime.attach(MIMEText(msg.body, "plain", "utf-8"))

    for path_str in msg.attachments:
        p = Path(path_str)
        if not p.exists():
            logger.warning("附件不存在, 跳过: {}", p)
            continue
        with p.open("rb") as f:
            data = f.read()
        part = MIMEApplication(data, Name=p.name)
        part["Content-Disposition"] = f'attachment; filename="{p.name}"'
        mime.attach(part)
    return mime


def _send_sync(msg: EmailMessage) -> None:
    """同步 SMTP 发送, 在线程池里跑"""
    if not settings.smtp_host or not settings.smtp_username:
        raise RuntimeError("SMTP 未配置, 请检查 .env (SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD)")

    mime = build_mime(msg)
    recipients = list(set(msg.to_emails + msg.cc_emails))

    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.login(settings.smtp_username, settings.smtp_password)
            s.sendmail(settings.smtp_from_email, recipients, mime.as_string())
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.starttls()
            s.login(settings.smtp_username, settings.smtp_password)
            s.sendmail(settings.smtp_from_email, recipients, mime.as_string())


async def send_email(msg: EmailMessage, db: AsyncSession, max_retry: int = 3) -> EmailLog:
    """异步发邮件 + 写 EmailLog + 失败重试"""
    from datetime import datetime, timezone

    log = EmailLog(
        template_code=msg.template_code,
        to_emails=msg.to_emails,
        cc_emails=msg.cc_emails,
        subject=msg.subject,
        body=msg.body,
        attachments=msg.attachments,
        booking_id=msg.booking_id,
        so_id=msg.so_id,
        context=msg.context or {},
        status=EmailStatus.PENDING,
    )
    db.add(log)
    await db.flush()

    last_err: str | None = None
    for attempt in range(1, max_retry + 1):
        try:
            await asyncio.to_thread(_send_sync, msg)
            log.status = EmailStatus.SENT
            log.sent_at = datetime.now(timezone.utc)
            log.retry_count = attempt - 1
            await db.commit()
            logger.info("邮件发送成功 to={} subject={}", msg.to_emails, msg.subject)
            return log
        except Exception as e:
            last_err = str(e)
            log.retry_count = attempt
            log.status = EmailStatus.RETRYING if attempt < max_retry else EmailStatus.FAILED
            log.error = last_err
            await db.commit()
            logger.warning("邮件发送失败 attempt={} err={}", attempt, e)
            if attempt < max_retry:
                await asyncio.sleep(2 ** attempt)  # 指数退避

    raise RuntimeError(f"邮件发送失败 (重试 {max_retry} 次): {last_err}")


async def render_and_send(
    template_code: str,
    context: dict[str, Any],
    to_emails: list[str],
    cc_emails: list[str] | None = None,
    attachments: list[str] | None = None,
    booking_id: str | None = None,
    so_id: str | None = None,
    db: AsyncSession | None = None,
) -> EmailLog:
    """从 EmailTemplate 渲染并发送"""
    from app.models.email_template import EmailTemplate

    if db is None:
        raise ValueError("db session is required")

    stmt = select(EmailTemplate).where(EmailTemplate.code == template_code, EmailTemplate.is_active.is_(True))
    tpl = (await db.execute(stmt)).scalar_one_or_none()
    if not tpl:
        raise ValueError(f"邮件模板不存在或未启用: {template_code}")

    subject, body = render_template(tpl.subject, tpl.body, context)
    msg = EmailMessage(
        to_emails=to_emails,
        cc_emails=cc_emails or [],
        subject=subject,
        body=body,
        attachments=attachments or [],
        template_code=template_code,
        booking_id=booking_id,
        so_id=so_id,
        context=context,
    )
    return await send_email(msg, db)
