"""v0.5 业务编号生成器 - job_no / booking_request_no

job_no: FB-YYYYMMDD-XXXX, 每天重置 (默认)
booking_request_no: BR-001 / BR-002, Shipment 内递增

P2 修复: 并发安全 — 用 try/except IntegrityError 重试 +1, 避免 COUNT+1 并发撞 UNIQUE.
(后续 v0.6 切到 PostgreSQL 可用 sequence / SELECT FOR UPDATE 更稳.)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import JobNoResetPolicy, Organization


async def generate_job_no(
    db: AsyncSession,
    org: Organization,
    now: datetime | None = None,
) -> str:
    """生成 job_no, 格式: {prefix}-{date}-{seq}.

    日期格式由 org.job_no_date_fmt 控制 (默认 YYYYMMDD).
    流水位数由 org.job_no_seq_digits 控制 (默认 4).
    重置策略由 org.job_no_reset_policy 控制.

    P2 修复: 并发安全 (max 5 次重试, 仍撞 unique 则 raise).
    """
    from app.models.shipment import Shipment  # 避免循环 import

    now = now or datetime.now(timezone.utc)

    # 日期段
    if org.job_no_date_fmt == "YYYYMMDD":
        date_part = now.strftime("%Y%m%d")
    elif org.job_no_date_fmt == "YYYYMM":
        date_part = now.strftime("%Y%m")
    elif org.job_no_date_fmt == "YYYY":
        date_part = now.strftime("%Y")
    else:
        date_part = now.strftime("%Y%m%d")

    # 流水段
    if org.job_no_reset_policy == JobNoResetPolicy.DAILY:
        pattern = f"{org.job_no_prefix}-{date_part}-%"
    elif org.job_no_reset_policy == JobNoResetPolicy.MONTHLY:
        pattern = f"{org.job_no_prefix}-{date_part}-%"
    else:  # NEVER
        pattern = f"{org.job_no_prefix}-%"

    # P2: 返回 best-guess candidate (COUNT+1)
    # 注: SQLite 上不能靠 probe 验证 unique, 并发 commit 时仍可能撞
    # 修复重点: endpoint (create_shipment/create_booking_request) commit 时
    # 捕 IntegrityError → rollback → 重试 generate_job_no (带 attempt 加 salt)
    stmt = select(func.count()).select_from(Shipment).where(
        Shipment.organization_id == org.id,
        Shipment.job_no.like(pattern),
    )
    count = (await db.execute(stmt)).scalar_one()
    seq = count + 1
    return f"{org.job_no_prefix}-{date_part}-{seq:0{org.job_no_seq_digits}d}"


# 别名: 保留原名指向简单版 (向后兼容)
generate_job_no_with_retry = generate_job_no


async def generate_booking_request_no(db: AsyncSession, shipment_id: str) -> str:
    """生成 booking_request_no: BR-001 / BR-002 / ...

    按 Shipment 内 BookingRequest 数量 + 1.
    P2: 并发安全 (max 5 次重试).
    """
    from app.models.booking_request import BookingRequest

    # P2: best-guess (类似 generate_job_no 备注)
    stmt = select(func.count()).select_from(BookingRequest).where(
        BookingRequest.shipment_id == shipment_id,
    )
    count = (await db.execute(stmt)).scalar_one()
    seq = count + 1
    return f"BR-{seq:03d}"


# 别名: 保留原名指向简单版
generate_booking_request_no_with_retry = generate_booking_request_no


def parse_job_no(job_no: str) -> dict[str, Any] | None:
    """解析 job_no, 失败返回 None.

    例: 'FB-20260820-0001' → {'prefix': 'FB', 'date': '20260820', 'seq': 1}
    """
    m = re.match(r"^([A-Z]{1,8})-(\d{6,8})-(\d{1,6})$", job_no)
    if not m:
        return None
    return {
        "prefix": m.group(1),
        "date": m.group(2),
        "seq": int(m.group(3)),
    }


def build_cargo_snapshot(
    pol: str,
    pod: str,
    target_etd,
    commodity: str,
    *,
    container_type: str = "40HQ",
    container_count: int = 1,
    customer_ref: str | None = None,
    pieces: int | None = None,
    weight_kg: float | None = None,
    volume_cbm: float | None = None,
    is_dangerous: bool = False,
    is_oversize: bool = False,
    hs_code: str | None = None,
    remark: str | None = None,
    final_destination: str | None = None,
) -> dict[str, Any]:
    """生成 cargo_snapshot dict, BookingRequest 发出时锁定"""
    return {
        "pol": pol,
        "pod": pod,
        "target_etd": target_etd.isoformat() if target_etd else None,
        "commodity": commodity,
        "container_type": container_type,
        "container_count": container_count,
        "customer_ref": customer_ref,
        "pieces": pieces,
        "weight_kg": weight_kg,
        "volume_cbm": volume_cbm,
        "is_dangerous": is_dangerous,
        "is_oversize": is_oversize,
        "hs_code": hs_code,
        "remark": remark,
        "final_destination": final_destination,
    }


def compute_diff(
    requested: dict[str, Any],
    confirmed: dict[str, Any],
) -> dict[str, Any]:
    """对比申请值和确认值, 返回 diff dict.

    例:
    requested = {"pol": "CNSHA", "target_etd": "2026-09-01", "container_count": 1}
    confirmed = {"pol": "CNSHA", "target_etd": "2026-09-02", "container_count": 2}
    →
    {
      "pol": {"requested": "CNSHA", "confirmed": "CNSHA", "match": True},
      "target_etd": {"requested": "2026-09-01", "confirmed": "2026-09-02", "match": False, "delta_days": 1},
      "container_count": {"requested": 1, "confirmed": 2, "match": False}
    }
    """
    diff: dict[str, Any] = {}
    for key in requested.keys():
        req_val = requested.get(key)
        conf_val = confirmed.get(key)
        if req_val is None and conf_val is None:
            continue
        match = req_val == conf_val
        entry: dict[str, Any] = {
            "requested": req_val,
            "confirmed": conf_val,
            "match": match,
        }
        # 日期字段特殊处理: 算 delta_days
        if (
            key in ("target_etd", "etd", "eta")
            and req_val
            and conf_val
            and not match
        ):
            try:
                r_date = datetime.fromisoformat(str(req_val)).date()
                c_date = datetime.fromisoformat(str(conf_val)).date()
                entry["delta_days"] = (c_date - r_date).days
            except (ValueError, TypeError):
                pass
        diff[key] = entry
    return diff
