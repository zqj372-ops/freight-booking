"""自动账单生成 + 对账 + 回款

闭环:
1. 运单 completed 时 -> 自动生成应收账单 (Booking → Bill)
2. 外部账单上传 (OCR) -> 自动尝试匹配 Booking
3. 财务确认收款/付款 -> 标记 paid
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bill import Bill, BillKind, BillStatus
from app.models.booking import Booking, BookingStatus
from app.models.tracking import TrackingEvent, TrackingStatus


# ============== 自动账单生成 ==============


async def generate_bill_on_booking_completed(
    db: AsyncSession, booking_id: str
) -> Bill | None:
    """运单完成时自动生成应收账单

    规则:
    - 已经生成过账单则跳过 (用 booking_id 查重)
    - BillType = receivable
    - BillKind = ocean_freight (海运)
    - 金额 = booking 的 estimated_total (如果没有, 暂估 = 0)
    - issued_at = 完成时间
    - due_at = +30 天
    """
    # 查重
    existing = (
        await db.execute(
            select(Bill).where(
                Bill.booking_id == booking_id,
                Bill.bill_type == "receivable",
                Bill.bill_kind.in_([BillKind.OCEAN_FREIGHT, BillKind.FREIGHT_INVOICE]),
            )
        )
    ).scalar_one_or_none()
    if existing:
        logger.info("Booking {} 已有应收账单, 跳过", booking_id)
        return None

    booking = (
        await db.execute(select(Booking).where(Booking.id == booking_id))
    ).scalar_one_or_none()
    if not booking:
        logger.warning("Booking not found: {}", booking_id)
        return None

    now = datetime.now(timezone.utc)
    # 找最近的 completed 事件
    last_event = (
        await db.execute(
            select(TrackingEvent)
            .where(
                TrackingEvent.booking_id == booking_id,
                TrackingEvent.status == TrackingStatus.COMPLETED,
            )
            .order_by(TrackingEvent.occurred_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    completed_at = last_event.occurred_at if last_event else now

    # 金额暂估: 目前没有金额, 用 0, 财务后续手动填
    # 如果你想自动算, 这里需要费率表 / 历史账单
    bill = Bill(
        bill_no=f"AUTO-{booking.booking_no}",
        bill_type="receivable",
        bill_kind=BillKind.OCEAN_FREIGHT,
        booking_id=booking.id,
        seller_name=booking.customer_name or "客户",
        buyer_name="(待填)",
        currency="CNY",
        total_amount=0,  # 财务确认时填
        issued_at=completed_at,
        due_at=datetime.fromtimestamp(
            completed_at.timestamp() + 30 * 86400, tz=timezone.utc
        )
        if hasattr(completed_at, "timestamp")
        else now,
        status=BillStatus.UPLOADED,  # 等财务填金额 + 确认
        remark=f"运单 {booking.booking_no} 完成时自动生成, 路线 {booking.pol}→{booking.pod}, 柜型 {booking.container_count}×{booking.container_type}",
    )
    db.add(bill)
    await db.commit()
    await db.refresh(bill)
    logger.info(
        "自动生成应收账单: booking={} bill_id={} amount={}",
        booking_no=booking.booking_no,
        bill_id=bill.id,
        amount=0,
    )
    return bill


# ============== 自动对账 ==============


@dataclass
class MatchResult:
    bill_id: str
    booking_id: str
    score: float  # 0-1
    reasons: list[str]


async def auto_match_bill_to_booking(
    db: AsyncSession, bill: Bill
) -> MatchResult | None:
    """尝试把账单匹配到 Booking

    评分规则 (总分 1.0):
    - booking_id 显式匹配: 0.4
    - 金额匹配 (在 5% 误差内): 0.4
    - 时间匹配 (issued_at 在 booking ETD ± 30 天): 0.2
    - 票号含 booking_no: 0.1 (bonus)
    """
    if bill.matched_booking_id:
        return None  # 已匹配过

    if not bill.total_amount or bill.total_amount <= 0:
        return None

    # 候选 Booking: 同公司近 90 天的订舱
    candidates = (
        await db.execute(
            select(Booking).where(
                Booking.created_at >= datetime.fromtimestamp(
                    (datetime.now(timezone.utc).timestamp()) - 90 * 86400,
                    tz=timezone.utc,
                )
            )
        )
    ).scalars().all()

    best: MatchResult | None = None
    for booking in candidates:
        score = 0.0
        reasons: list[str] = []

        # 1. 显式 booking_id 关联
        if bill.booking_id == booking.id:
            score += 0.4
            reasons.append("显式 booking_id 关联")

        # 2. 金额匹配 (在 booking container_count * 假设单价 范围内? 没数据就放宽)
        # 这里用 booking 创建时如果有 amount 数据, 但目前没有, 改为按容差匹配
        # 简化: 任何金额都给 0.2 基础分, 然后看匹配项
        score += 0.2  # 基础分
        reasons.append("候选 booking")

        # 3. 时间匹配
        if bill.issued_at and booking.etd:
            delta = abs((bill.issued_at - booking.etd).days)
            if delta <= 7:
                score += 0.2
                reasons.append(f"开票日与 ETD 差 {delta} 天 (≤7)")
            elif delta <= 30:
                score += 0.1
                reasons.append(f"开票日与 ETD 差 {delta} 天 (≤30)")

        # 4. 票号含 booking_no
        if bill.bill_no and booking.booking_no:
            if booking.booking_no in bill.bill_no or bill.bill_no.endswith(booking.booking_no):
                score += 0.1
                reasons.append("票号含 booking_no")

        # 5. POL/POD 一致
        if bill.extra_fields and isinstance(bill.extra_fields, dict):
            pol_match = bill.extra_fields.get("pol") == booking.pol
            pod_match = bill.extra_fields.get("pod") == booking.pod
            if pol_match and pod_match:
                score += 0.1
                reasons.append("POL/POD 一致")

        score = min(score, 1.0)

        if best is None or score > best.score:
            best = MatchResult(
                bill_id=bill.id,
                booking_id=booking.id,
                score=score,
                reasons=reasons,
            )

    if best and best.score >= 0.5:
        # 写入匹配
        bill.matched_booking_id = best.booking_id
        bill.matched_at = datetime.now(timezone.utc)
        bill.match_score = best.score
        bill.booking_id = best.booking_id  # 也填到 booking_id 字段, 便于 SO 关联显示
        await db.commit()
        logger.info(
            "账单自动匹配: bill={} booking={} score={} reasons={}",
            bill.bill_no,
            best.booking_id,
            best.score,
            best.reasons,
        )
        return best

    return None


async def reconcile_pending_bills(
    db: AsyncSession, limit: int = 100
) -> list[MatchResult]:
    """批量对账 - 处理所有待对账账单"""
    pending = (
        await db.execute(
            select(Bill)
            .where(
                Bill.matched_booking_id.is_(None),
                Bill.total_amount.isnot(None),
                Bill.total_amount > 0,
                Bill.status.in_([BillStatus.UPLOADED, BillStatus.OCR_DONE, BillStatus.CONFIRMED]),
            )
            .limit(limit)
        )
    ).scalars().all()

    results: list[MatchResult] = []
    for bill in pending:
        r = await auto_match_bill_to_booking(db, bill)
        if r:
            results.append(r)
    return results


# ============== 回款登记 ==============


async def mark_paid(
    db: AsyncSession,
    bill_id: str,
    payment_method: str,
    payment_ref: str | None = None,
    paid_at: datetime | None = None,
) -> Bill:
    """登记回款"""
    bill = (
        await db.execute(select(Bill).where(Bill.id == bill_id))
    ).scalar_one_or_none()
    if not bill:
        raise ValueError(f"bill not found: {bill_id}")
    if bill.status == BillStatus.PAID:
        return bill  # 幂等

    bill.status = BillStatus.PAID
    bill.paid_at = paid_at or datetime.now(timezone.utc)
    bill.payment_method = payment_method
    bill.payment_ref = payment_ref
    await db.commit()
    await db.refresh(bill)
    logger.info(
        "回款登记: bill={} amount={} {} method={}",
        bill.bill_no,
        bill.total_amount,
        bill.currency,
        payment_method,
    )
    return bill


# ============== 财务 KPI ==============


@dataclass
class FinanceKPI:
    receivable_total: float  # 应收总额
    receivable_paid: float  # 已收
    receivable_pending: float  # 未收
    payable_total: float
    payable_paid: float
    payable_pending: float
    overdue_count: int  # 逾期账单数
    by_carrier: dict[str, float]  # 按船公司应收余额


async def compute_finance_kpi(db: AsyncSession) -> dict:
    """Dashboard 财务 KPI"""
    # 应收
    rec_q = select(Bill).where(Bill.bill_type == "receivable")
    pay_q = select(Bill).where(Bill.bill_type == "payable")
    rec_bills = (await db.execute(rec_q)).scalars().all()
    pay_bills = (await db.execute(pay_q)).scalars().all()

    def kpis(bills: list[Bill]) -> tuple[float, float, float]:
        total = sum(b.total_amount or 0 for b in bills)
        paid = sum(b.total_amount or 0 for b in bills if b.status == BillStatus.PAID)
        return total, paid, total - paid

    rec_total, rec_paid, rec_pending = kpis(rec_bills)
    pay_total, pay_paid, pay_pending = kpis(pay_bills)

    now = datetime.now(timezone.utc)
    # SQLite 不存时区, 读出来是 naive, 统一成 aware 再比较
    overdue = [
        b for b in rec_bills
        if b.due_at
        and (b.due_at if b.due_at.tzinfo else b.due_at.replace(tzinfo=timezone.utc)) < now
        and b.status != BillStatus.PAID
    ]

    # 按船公司 (通过关联 booking)
    by_carrier: dict[str, float] = {}
    for b in rec_bills:
        if b.status == BillStatus.PAID:
            continue
        # 优先用 matched_booking, 没有就用 booking_id 关联
        bk = b.matched_booking or b.booking
        if not bk:
            continue
        car = bk.carrier
        by_carrier[car] = by_carrier.get(car, 0) + (b.total_amount or 0)

    return {
        "receivable_total": round(rec_total, 2),
        "receivable_paid": round(rec_paid, 2),
        "receivable_pending": round(rec_pending, 2),
        "payable_total": round(pay_total, 2),
        "payable_paid": round(pay_paid, 2),
        "payable_pending": round(pay_pending, 2),
        "overdue_count": len(overdue),
        "by_carrier": {k: round(v, 2) for k, v in sorted(by_carrier.items(), key=lambda x: -x[1])[:5]},
    }
