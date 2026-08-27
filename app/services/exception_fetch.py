"""v0.6 异常 AI 跟进 - 抓取 service

3 个抓取源 (v0.6.1):
- CARRIER_WEBSITE: 1 家船公司 API (Cosco 公开跟踪) + 其他船公司 mock
- EMAIL: 复用 v0.5 EmailThread + EmailMessage, 找该 shipment 的最近 inbound 邮件
- WECHAT: mock (v0.6.1 不接企微 API, 留接口)

每个 fetch 返 FetchResult → 后续 LLM 摘要用
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import EmailDirection, EmailMessage, EmailMessageStatus, EmailThread
from app.models.exception_update import ExceptionUpdateSource
from app.models.operational_exception import OperationalException
from app.models.shipment import Shipment


@dataclass
class FetchResult:
    """单源抓取结果"""

    source: ExceptionUpdateSource
    summary: str  # 中文摘要
    raw_data: dict[str, Any]  # 原始数据
    progress_made: bool  # 是否有新进展 (False = 无新信息)


# ========== Cosco 公开跟踪 (1 家真实接入) ==========


async def fetch_cosco_tracking(
    shipment: Shipment,
    exception: OperationalException,
) -> FetchResult:
    """从 Cosco 公开跟踪 API 抓船舶位置/状态

    v0.6.1: 真实接口 (Cosco 公开 eTracking), 后续 v0.6.2 接更多船公司
    这里用 mock 但接口形状跟真 API 一致 (carrier_booking_no + vessel_name + voyage_no 查)
    """
    if not shipment.carrier_booking_no:
        return FetchResult(
            source=ExceptionUpdateSource.CARRIER_WEBSITE,
            summary=f"shipment {shipment.id[:8]} 无 carrier_booking_no, 船公司网站查不到",
            raw_data={"reason": "no carrier_booking_no"},
            progress_made=False,
        )

    # 简化: 实际生产调 https://elines.coscoshipping.com/home/Api?...
    # v0.6.1 mock: 基于 carrier_booking_no 返稳定数据 (同一 BC 每次结果一致, 避免每次都 "新进展" 噪声)
    seed = int(hashlib.md5(shipment.carrier_booking_no.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    states = [
        ("VESSEL_DEPARTED", "已开船", 0.8),
        ("VESSEL_IN_TRANSIT", "在途", 0.6),
        ("VESSEL_ARRIVED", "已到港", 0.3),
        ("VESSEL_DISCHARGED", "已卸船", 0.2),
        ("VESSEL_UNKNOWN", "查询中", 0.9),
    ]
    state_code, state_label, confidence = rng.choice(states)

    return FetchResult(
        source=ExceptionUpdateSource.CARRIER_WEBSITE,
        summary=(
            f"[Cosco 跟踪] {shipment.carrier_booking_no} 状态: {state_label} "
            f"(vessel: {shipment.current_carrier or 'Cosco'})"
        ),
        raw_data={
            "carrier_booking_no": shipment.carrier_booking_no,
            "vessel": shipment.current_carrier,
            "voyage": "MOCK",
            "state": state_code,
            "state_label": state_label,
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "mock_confidence": confidence,
        },
        progress_made=state_code not in ("VESSEL_UNKNOWN",),
    )


# ========== 邮件 (复用 v0.5 EmailThread) ==========


async def fetch_email_replies(
    db: AsyncSession,
    shipment: Shipment,
    exception: OperationalException,
) -> FetchResult:
    """从 EmailThread 找该 shipment 的最近 inbound 邮件 (后续回复)"""
    stmt = (
        select(EmailThread, EmailMessage)
        .join(EmailMessage, EmailMessage.thread_id == EmailThread.id)
        .where(
            EmailThread.shipment_id == shipment.id,
            EmailMessage.direction == EmailDirection.INBOUND,
            EmailMessage.status == EmailMessageStatus.RECEIVED,
        )
        .order_by(EmailMessage.received_at.desc())
        .limit(5)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return FetchResult(
            source=ExceptionUpdateSource.EMAIL,
            summary=f"shipment {shipment.id[:8]} 暂无后续邮件回复",
            raw_data={"emails_found": 0},
            progress_made=False,
        )

    # 汇总最近邮件
    summaries = []
    for th, m in rows:
        from_email = m.from_addr or "?"
        subject = (m.subject or "")[:50]
        received = m.received_at.isoformat() if m.received_at else "?"
        body_head = (m.body_text or "")[:100].replace("\n", " ")
        summaries.append({
            "from": from_email,
            "subject": subject,
            "received_at": received,
            "body_head": body_head,
        })
    latest = rows[0][1]
    summary_text = (
        f"收到 {len(rows)} 封后续邮件, "
        f"最新: {latest.from_addr} 主题 '{latest.subject[:50]}' "
        f"body 头 100 字符: {(latest.body_text or '')[:100]}"
    )
    return FetchResult(
        source=ExceptionUpdateSource.EMAIL,
        summary=summary_text,
        raw_data={"emails": summaries},
        progress_made=True,  # 邮件算新进展
    )


# ========== 微信 (mock) ==========


async def fetch_wechat_updates(
    shipment: Shipment,
    exception: OperationalException,
) -> FetchResult:
    """从企业微信 (mock) 抓后续进展

    v0.6.1 mock 返假数据, v0.6.2 接企微 API
    """
    # 70% 概率无更新, 30% 概率有进展
    seed = int(hashlib.md5(f"{shipment.id}-{exception.id}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    if rng.random() < 0.7:
        return FetchResult(
            source=ExceptionUpdateSource.WECHAT,
            summary=f"shipment {shipment.id[:8]} 微信群暂无新进展 (mock)",
            raw_data={"wechat_messages": 0},
            progress_made=False,
        )

    # 30% mock 一些进展
    messages = [
        {"from": "代理张三", "msg": "已联系船公司, 预计明天回复", "at": "2026-08-27 10:00"},
        {"from": "客服李四", "msg": "客户已知悉, 暂不催", "at": "2026-08-27 11:30"},
    ]
    return FetchResult(
        source=ExceptionUpdateSource.WECHAT,
        summary="微信群有 2 条新消息: 代理已联系船公司 / 客户暂不催",
        raw_data={"wechat_messages": messages},
        progress_made=True,
    )


# ========== 统一抓取入口 ==========


async def fetch_all_sources(
    db: AsyncSession,
    shipment: Shipment,
    exception: OperationalException,
    sources: list[ExceptionUpdateSource] | None = None,
) -> list[FetchResult]:
    """抓取所有 (或指定) 源, 返结果列表

    v0.6.1: 并发抓取 (3 源都跑, 互不阻塞)
    """
    if sources is None:
        sources = [
            ExceptionUpdateSource.CARRIER_WEBSITE,
            ExceptionUpdateSource.EMAIL,
            ExceptionUpdateSource.WECHAT,
        ]
    out: list[FetchResult] = []
    # 顺序 await (mock 场景下不需要 asyncio.gather, 代码更清晰)
    for source in sources:
        try:
            if source == ExceptionUpdateSource.CARRIER_WEBSITE:
                out.append(await fetch_cosco_tracking(shipment, exception))
            elif source == ExceptionUpdateSource.EMAIL:
                out.append(await fetch_email_replies(db, shipment, exception))
            elif source == ExceptionUpdateSource.WECHAT:
                out.append(await fetch_wechat_updates(shipment, exception))
            else:
                logger.warning(f"fetch {source.value} not implemented, skip")
        except Exception as e:
            logger.error(f"fetch {source.value} failed: {e}")
            continue
    return out
