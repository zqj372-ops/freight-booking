"""Finance - 回款 + 对账 + KPI"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.schemas.bill import (
    FinanceKPIResponse,
    PayBillRequest,
    ReconcileResult,
)
from app.services.auto_bill_service import (
    compute_finance_kpi,
    mark_paid,
    reconcile_pending_bills,
)

router = APIRouter()


@router.post("/bills/{bill_id}/pay", response_model=dict)
async def pay_bill(
    bill_id: str,
    payload: PayBillRequest,
    db: AsyncSession = Depends(db_session),
) -> dict:
    """登记回款"""
    try:
        bill = await mark_paid(
            db,
            bill_id=bill_id,
            payment_method=payload.payment_method,
            payment_ref=payload.payment_ref,
            paid_at=payload.paid_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "id": bill.id,
        "bill_no": bill.bill_no,
        "status": bill.status.value,
        "paid_at": bill.paid_at.isoformat() if bill.paid_at else None,
        "payment_method": bill.payment_method,
        "payment_ref": bill.payment_ref,
    }


@router.post("/reconcile", response_model=ReconcileResult)
async def reconcile(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(db_session),
) -> ReconcileResult:
    """批量对账 - 自动把未匹配账单 try match Booking"""
    results = await reconcile_pending_bills(db, limit=limit)
    return ReconcileResult(
        matched=len(results),
        skipped=0,
        results=[
            {
                "bill_id": r.bill_id,
                "booking_id": r.booking_id,
                "score": r.score,
                "reasons": r.reasons,
            }
            for r in results
        ],
    )


@router.get("/dashboard", response_model=FinanceKPIResponse)
async def finance_dashboard(
    db: AsyncSession = Depends(db_session),
) -> FinanceKPIResponse:
    """财务 KPI - 应收/已收/未收 + 逾期 + 按船公司余额"""
    data = await compute_finance_kpi(db)
    return FinanceKPIResponse(**data)
