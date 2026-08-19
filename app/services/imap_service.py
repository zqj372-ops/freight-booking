"""IMAP 自动拉邮件服务

流程:
1. 拉取邮件 (imapclient)
2. 按主题/发件人过滤
3. 按 message_id 去重 (ProcessedEmail 表)
4. 提取附件 (PDF/图片) → uploads/so/
5. 创建 SO 记录 (source='email', 自动跑 OCR)

支持 mock 模式: 读 ./samples/imap/*.eml 文件 (不连真实邮箱)
"""

from __future__ import annotations

import asyncio
import email as email_lib
import email.utils
import hashlib
import imaplib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email_ingestion import (
    EmailIngestion,
    IngestionSource,
    IngestionStatus,
    ProcessedEmail,
)
from app.models.so import SO, SOStatus


# 附件白名单扩展
ATTACHMENT_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


@dataclass
class ParsedAttachment:
    filename: str
    content: bytes
    mime: str = "application/octet-stream"


@dataclass
class ParsedEmail:
    message_id: str
    from_addr: str
    subject: str
    received_at: datetime
    body_text: str
    attachments: list[ParsedAttachment] = field(default_factory=list)


def _decode_header_value(v: str | None) -> str:
    if not v:
        return ""
    parts = decode_header(v)
    decoded: list[str] = []
    for s, enc in parts:
        if isinstance(s, bytes):
            try:
                decoded.append(s.decode(enc or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                decoded.append(s.decode("utf-8", errors="replace"))
        else:
            decoded.append(s)
    return "".join(decoded).strip()


def _hash_message_id(mid: str) -> str:
    return hashlib.sha256(mid.encode("utf-8")).hexdigest()


def parse_eml_file(path: Path) -> ParsedEmail:
    """解析 .eml 文件 → ParsedEmail"""
    raw = path.read_bytes()
    msg = email_lib.message_from_bytes(raw)

    message_id = msg.get("Message-ID", "").strip() or f"no-id-{path.name}-{path.stat().st_mtime}"
    from_addr = _decode_header_value(msg.get("From", ""))
    subject = _decode_header_value(msg.get("Subject", ""))
    date_hdr = msg.get("Date", "")
    try:
        received_at = email.utils.parsedate_to_datetime(date_hdr) if date_hdr else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        received_at = datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    body_text = ""
    attachments: list[ParsedAttachment] = []
    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()

        if part.is_multipart():
            continue

        filename = part.get_filename()
        if filename or "attachment" in disposition:
            # 附件
            payload = part.get_payload(decode=True) or b""
            if not filename:
                ext = ".bin"
            else:
                fn_decoded = _decode_header_value(filename)
                ext = Path(fn_decoded).suffix.lower() or ".bin"
            attachments.append(
                ParsedAttachment(
                    filename=fn_decoded or f"attach{ext}",
                    content=payload,
                    mime=content_type,
                )
            )
        elif content_type == "text/plain" and not body_text:
            try:
                body_text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
            except (LookupError, AttributeError):
                body_text = part.get_payload(decode=True).decode("utf-8", errors="replace")

    return ParsedEmail(
        message_id=message_id,
        from_addr=from_addr,
        subject=subject,
        received_at=received_at,
        body_text=body_text,
        attachments=attachments,
    )


def filter_email(parsed: ParsedEmail, from_whitelist: list[str], subject_keywords: list[str]) -> bool:
    """返回 True 表示要拉"""
    # 发件人白名单
    if from_whitelist:
        addr_lc = parsed.from_addr.lower()
        if not any(w.strip().lower() in addr_lc for w in from_whitelist):
            return False
    # 主题关键词
    if subject_keywords:
        subj_lc = parsed.subject.lower()
        if not any(kw.strip().lower() in subj_lc for kw in subject_keywords):
            return False
    return True


# ===== Real IMAP =====


class ImapClient:
    """同步 imaplib 包装, 内部在线程池跑"""

    def __init__(self) -> None:
        self._conn: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
        self._cfg = settings

    def _connect(self) -> None:
        if self._conn is not None:
            return
        if self._cfg.imap_use_ssl:
            self._conn = imaplib.IMAP4_SSL(self._cfg.imap_host, self._cfg.imap_port)
        else:
            self._conn = imaplib.IMAP4(self._cfg.imap_host, self._cfg.imap_port)
        if not self._cfg.imap_username or not self._cfg.imap_password:
            raise RuntimeError("IMAP 未配置 (IMAP_USERNAME / IMAP_PASSWORD)")
        self._conn.login(self._cfg.imap_username, self._cfg.imap_password)

    def _select_mailbox(self) -> None:
        if self._conn is None:
            self._connect()
        assert self._conn is not None
        self._conn.select(self._cfg.imap_mailbox)

    def _search_unseen(self) -> list[bytes]:
        if self._conn is None:
            self._connect()
        assert self._conn is not None
        typ, data = self._conn.search(None, "UNSEEN")
        if typ != "OK":
            return []
        return data[0].split()

    def _fetch_message(self, num: bytes) -> bytes:
        if self._conn is None:
            self._connect()
        assert self._conn is not None
        typ, data = self._conn.fetch(num, "(RFC822)")
        if typ != "OK" or not data or not data[0]:
            return b""
        # data[0] 可能是 tuple (b'...', b'raw email') 或单独 bytes
        if isinstance(data[0], tuple) and len(data[0]) >= 2:
            return data[0][1]
        return data[0]

    def _logout(self) -> None:
        if self._conn is not None:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def fetch_latest(self, max_n: int) -> list[ParsedEmail]:
        """拉最近 N 封未读邮件"""
        self._select_mailbox()
        nums = self._search_unseen()
        nums = nums[-max_n:]  # 最新的在前
        results: list[ParsedEmail] = []
        try:
            for num in nums:
                raw = self._fetch_message(num)
                if not raw:
                    continue
                msg = email_lib.message_from_bytes(raw)
                mid = msg.get("Message-ID", "").strip() or f"imap-{num.decode()}"
                parsed = ParsedEmail(
                    message_id=mid,
                    from_addr=_decode_header_value(msg.get("From", "")),
                    subject=_decode_header_value(msg.get("Subject", "")),
                    received_at=email.utils.parsedate_to_datetime(msg.get("Date", ""))
                    or datetime.now(timezone.utc),
                    body_text="",
                    attachments=[],
                )
                # 解析附件
                for part in msg.walk():
                    if part.is_multipart():
                        continue
                    fn = part.get_filename()
                    if fn:
                        fn_decoded = _decode_header_value(fn)
                        ext = Path(fn_decoded).suffix.lower()
                        if ext in ATTACHMENT_EXT:
                            parsed.attachments.append(
                                ParsedAttachment(
                                    filename=fn_decoded,
                                    content=part.get_payload(decode=True) or b"",
                                    mime=part.get_content_type(),
                                )
                            )
                results.append(parsed)
        finally:
            self._logout()
        return results


# ===== Ingestion 主流程 =====


@dataclass
class IngestionResult:
    ingestion_id: str
    source: IngestionSource
    total_fetched: int = 0
    new_count: int = 0
    skip_count: int = 0
    error_count: int = 0
    error: str | None = None
    so_ids: list[str] = field(default_factory=list)


async def _save_attachment(file_bytes: bytes, filename: str) -> Path:
    """保存附件到 uploads/so/, 返回路径"""
    suffix = Path(filename).suffix.lower() or ".bin"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    target_dir = settings.upload_dir / "so"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{timestamp}_{filename.replace('/', '_')}{suffix}"
    target.write_bytes(file_bytes)
    return target


async def _already_processed(db: AsyncSession, msg_hash: str) -> ProcessedEmail | None:
    stmt = select(ProcessedEmail).where(ProcessedEmail.message_id_hash == msg_hash)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _process_one(
    db: AsyncSession,
    parsed: ParsedEmail,
    ingestion: EmailIngestion,
    source: IngestionSource,
) -> str | None:
    """处理一封邮件, 返回新创建的 SO id (None = 跳过)"""
    mid_hash = _hash_message_id(parsed.message_id)

    # 去重
    existing = await _already_processed(db, mid_hash)
    if existing:
        logger.info("邮件已处理过, 跳过: {}", parsed.message_id)
        ingestion.skipped_message_ids.append(parsed.message_id)
        return None

    if not parsed.attachments:
        # 没附件, 跳过 (但记录到 ProcessedEmail 防重复扫)
        pe = ProcessedEmail(
            message_id=parsed.message_id,
            message_id_hash=mid_hash,
            from_addr=parsed.from_addr,
            subject=parsed.subject,
            received_at=parsed.received_at,
            source=source,
            processed_at=datetime.now(timezone.utc),
            ingestion_id=ingestion.id,
        )
        db.add(pe)
        logger.info("邮件无附件, 跳过: {}", parsed.subject)
        return None

    # 找出第一个支持的附件
    target_attach = None
    for att in parsed.attachments:
        if Path(att.filename).suffix.lower() in ATTACHMENT_EXT:
            target_attach = att
            break
    if not target_attach:
        return None

    # 保存文件
    saved_path = await _save_attachment(target_attach.content, target_attach.filename)
    so = SO(
        source="email",
        source_email=parsed.from_addr,
        source_subject=parsed.subject,
        file_path=str(saved_path),
        file_name=target_attach.filename,
        file_mime=target_attach.mime,
        file_size=len(target_attach.content),
        status=SOStatus.PENDING,
    )
    db.add(so)
    await db.flush()

    # 记录到 ProcessedEmail
    pe = ProcessedEmail(
        message_id=parsed.message_id,
        message_id_hash=mid_hash,
        from_addr=parsed.from_addr,
        subject=parsed.subject,
        received_at=parsed.received_at,
        source=source,
        so_id=so.id,
        processed_at=datetime.now(timezone.utc),
        ingestion_id=ingestion.id,
    )
    db.add(pe)
    return so.id


async def _trigger_ocr_for_so(so_id: str) -> None:
    """复用 SO 上传后的后台 OCR 任务"""
    from app.api.v1.so import _run_ocr

    so = await _get_so(so_id)
    if so:
        await _run_ocr(so_id, so.file_path)


async def _get_so(so_id: str) -> SO | None:
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        stmt = select(SO).where(SO.id == so_id)
        return (await db.execute(stmt)).scalar_one_or_none()


async def run_ingestion(
    db: AsyncSession,
    source: IngestionSource | None = None,
) -> IngestionResult:
    """执行一次拉取 - 真实或 mock, 走 scheduler 或手动触发都调这个"""
    # 决定模式
    has_real_creds = bool(settings.imap_username and settings.imap_password)
    is_mock = source == IngestionSource.MOCK or (
        source is None and (settings.imap_mock_mode or not has_real_creds)
    )
    if source is None:
        source = IngestionSource.MOCK if is_mock else IngestionSource.IMAP

    started_at = datetime.now(timezone.utc)
    ingestion = EmailIngestion(
        source=source,
        mailbox=settings.imap_mailbox if not is_mock else "MOCK",
        status=IngestionStatus.RUNNING,
        started_at=started_at,
    )
    db.add(ingestion)
    await db.commit()
    await db.refresh(ingestion)

    result = IngestionResult(ingestion_id=ingestion.id, source=source)

    try:
        # 拉邮件
        from_whitelist = [w.strip() for w in settings.imap_filter_from.split(",") if w.strip()]
        subject_kw = [k.strip() for k in settings.imap_filter_subject_keywords.split(",") if k.strip()]

        if is_mock:
            emails = _mock_fetch(settings.imap_mock_dir)
        else:
            client = ImapClient()

            def _do_fetch() -> list[ParsedEmail]:
                return client.fetch_latest(settings.imap_max_per_poll)

            emails = await asyncio.to_thread(_do_fetch)

        result.total_fetched = len(emails)
        logger.info("IMAP 拉取完成 source={} count={}", source, len(emails))

        for parsed in emails:
            try:
                if not filter_email(parsed, from_whitelist, subject_kw):
                    result.skip_count += 1
                    continue
                new_so_id = await _process_one(db, parsed, ingestion, source)
                if new_so_id:
                    result.new_count += 1
                    result.so_ids.append(new_so_id)
                    # 触发 OCR (后台)
                    asyncio.create_task(_trigger_ocr_for_so(new_so_id))
                else:
                    result.skip_count += 1
            except Exception as e:
                result.error_count += 1
                logger.exception("处理邮件失败: {}", parsed.subject)
                logger.error("  err: {}", e)

        await db.commit()
        ingestion.status = IngestionStatus.SUCCESS
        ingestion.finished_at = datetime.now(timezone.utc)
        ingestion.total_fetched = result.total_fetched
        ingestion.new_count = result.new_count
        ingestion.skip_count = result.skip_count
        ingestion.error_count = result.error_count
        ingestion.so_ids = result.so_ids
        ingestion.skipped_message_ids = [
            m for m in (ingestion.skipped_message_ids or [])
        ]
        await db.commit()
        logger.info(
            "IMAP ingestion 完成: new={} skip={} err={}",
            result.new_count,
            result.skip_count,
            result.error_count,
        )
    except Exception as e:
        result.error = str(e)
        logger.exception("IMAP ingestion 失败: {}", e)
        try:
            ingestion.status = IngestionStatus.FAILED
            ingestion.finished_at = datetime.now(timezone.utc)
            ingestion.error = str(e)
            await db.commit()
        except Exception:
            pass
    return result


def _mock_fetch(mock_dir: Path) -> list[ParsedEmail]:
    """从本地 .eml 文件模拟拉取"""
    if not mock_dir.exists():
        logger.warning("mock 目录不存在: {}", mock_dir)
        return []
    results: list[ParsedEmail] = []
    for eml in sorted(mock_dir.glob("*.eml")):
        try:
            results.append(parse_eml_file(eml))
        except Exception as e:
            logger.exception("解析 .eml 失败: {}: {}", eml, e)
    return results
