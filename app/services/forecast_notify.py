"""v0.6 预报 截单通知 service

截单预警 (CY Cut-off 前 N 天):
- 复用 v0.5 email_service.send_email (P1#3 已修, 真调 SMTP, dry_run 安全)
- 通知模板: 计划 + 仓库 + 车行 + 单证 4 类接收方
- 草稿模式 (dry_run=true): 生成 email log 但不改 BR 状态
- 实发模式 (dry_run=false): 真发 SMTP, 失败返 502
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email_log import EmailLog, EmailStatus
from app.models.forecast import Forecast
from app.models.organization import Organization
from app.models.partner import Partner


@dataclass
class CutOffNotification:
    """截单通知结果"""

    forecast_id: str
    recipients: list[str]  # 实际发送/草稿的 to
    subject: str
    body: str
    email_log_id: str
    status: str  # sent / failed / pending (dry_run)
    error: str | None = None


# 默认收件人 (4 类: 计划/仓库/车行/单证)
# 实际生产应从 organization 表 / 配置文件读
DEFAULT_RECIPIENTS = {
    "planner": ["planner@mycompany.com"],         # 计划
    "warehouse": ["warehouse@mycompany.com"],   # 仓库
    "trucker": ["trucker@mycompany.com"],         # 车行
    "docs": ["docs@mycompany.com"],                # 单证
}


def build_cutoff_email(
    forecast: Forecast,
    *,
    days_remaining: int,
    recipients: dict[str, list[str]] | None = None,
) -> tuple[str, str, list[str]]:
    """生成截单邮件 (subject, body, all_recipients)

    - subject: 截单提醒 [JOB-XXX] CNSHA→USLAX 3 票 9/15 开船 (cutoff 9/12 还 3 天)
    - body: 表格列出每个 forecast + 关键字段
    - recipients: 4 类接收方 all merged
    """
    to_all: list[str] = []
    if recipients:
        for k, vs in recipients.items():
            to_all.extend(vs)
    else:
        for vs in DEFAULT_RECIPIENTS.values():
            to_all.extend(vs)

    subject = (
        f"[截单提醒] {forecast.pol}→{forecast.pod} "
        f"{forecast.container_count}×{forecast.container_type} "
        f"ETD {forecast.target_etd} (还 {days_remaining} 天)"
    )

    body_lines = [
        f"客户: {forecast.customer_name}",
        f"航线: {forecast.pol} → {forecast.pod}",
        f"柜型/数量: {forecast.container_count} × {forecast.container_type}",
        f"预报开船 (ETD): {forecast.target_etd}",
        f"",
        f"⚠ 距 CY Cut-off 还 {days_remaining} 天, 请及时确认:",
        "  - 计划: 确认船期/舱位",
        "  - 仓库: 准备收货",
        "  - 车行: 安排提柜",
        "  - 单证: 准备 SI/VGM",
        "",
        f"预报单 ID: {forecast.id}",
        f"预报单号: (内部分配)",
    ]
    body = "\n".join(body_lines)
    return subject, body, to_all


async def send_cutoff_notifications(
    db: AsyncSession,
    organization: Organization,
    *,
    forecast_ids: list[str],
    dry_run: bool = True,
    recipients: dict[str, list[str]] | None = None,
) -> list[CutOffNotification]:
    """给一组 forecast 发送截单通知

    P1#3 安全: dry_run 模式 (default=True) 不真发 SMTP, 仅写 PENDING log
    切到 dry_run=False 才真发, 失败返 502, 不改 forecast 状态
    """
    today = date.today()
    results: list[CutOffNotification] = []
    for fid in forecast_ids:
        f = (await db.execute(
            select(Forecast).where(Forecast.id == fid)
        )).scalar_one_or_none()
        if not f or not f.shipment_id:
            continue
        # 查关联 Shipment 的 cy_cutoff_at
        from app.models.shipment import Shipment
        s = (await db.execute(
            select(Shipment).where(Shipment.id == f.shipment_id)
        )).scalar_one_or_none()
        if not s or not s.cy_cutoff_at:
            continue
        days_remaining = (s.cy_cutoff_at.date() - today).days
        if days_remaining < 0 or days_remaining > 7:
            continue  # 只发 0-7 天内的预警

        subject, body, to_all = build_cutoff_email(
            f, days_remaining=days_remaining, recipients=recipients,
        )

        # 写 EmailLog
        if dry_run:
            log = EmailLog(
                template_code="cutoff_reminder",
                to_emails=to_all,
                cc_emails=[],
                subject=subject,
                body=body,
                status=EmailStatus.PENDING,
                booking_id=f.shipment_id,  # v0.4 字段, 暂用 shipment_id 占位
                context={
                    "dry_run": True,
                    "forecast_id": f.id,
                    "days_remaining": days_remaining,
                },
            )
            db.add(log)
            await db.commit()
            await db.refresh(log)
            results.append(CutOffNotification(
                forecast_id=f.id,
                recipients=to_all,
                subject=subject,
                body=body,
                email_log_id=log.id,
                status="pending",
            ))
            logger.info(f"forecast {f.id} 截单通知 (draft) 创建, log={log.id}")
        else:
            # 复用 v0.5 email_service.send_email (P1#3 已修 真 SMTP)
            from app.services.email_service import EmailMessage, send_email
            smtp_msg = EmailMessage(
                to_emails=to_all,
                cc_emails=[],
                subject=subject,
                body=body,
                attachments=[],
                is_html=False,
                template_code="cutoff_reminder",
                booking_id=f.shipment_id,
                context={"forecast_id": f.id, "days_remaining": days_remaining},
            )
            try:
                log = await send_email(smtp_msg, db)
                await db.refresh(log)
                results.append(CutOffNotification(
                    forecast_id=f.id,
                    recipients=to_all,
                    subject=subject,
                    body=body,
                    email_log_id=log.id,
                    status="sent" if log.status == EmailStatus.SENT else "failed",
                    error=log.error,
                ))
            except Exception as e:
                logger.error(f"forecast {f.id} 截单邮件发送失败: {e}")
                # 写一条 FAILED log 留痕
                log = EmailLog(
                    template_code="cutoff_reminder",
                    to_emails=to_all,
                    cc_emails=[],
                    subject=subject,
                    body=body,
                    status=EmailStatus.FAILED,
                    error=str(e)[:500],
                    booking_id=f.shipment_id,
                    context={"forecast_id": f.id, "error_at": "smtp_send"},
                )
                db.add(log)
                await db.commit()
                await db.refresh(log)
                results.append(CutOffNotification(
                    forecast_id=f.id,
                    recipients=to_all,
                    subject=subject,
                    body=body,
                    email_log_id=log.id,
                    status="failed",
                    error=str(e),
                ))

    return results
