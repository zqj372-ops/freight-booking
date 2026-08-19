"""Bill Schemas"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.bill import BillKind, BillStatus


class BillBase(BaseModel):
    bill_no: str
    bill_kind: BillKind = BillKind.OTHER
    bill_type: str = "receivable"  # receivable / payable
    booking_id: str | None = None
    seller_name: str | None = None
    seller_tax_no: str | None = None
    buyer_name: str | None = None
    buyer_tax_no: str | None = None
    currency: str = "CNY"
    total_amount: float | None = None
    tax_amount: float | None = None
    amount_excl_tax: float | None = None
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    extra_fields: dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime | None = None
    due_at: datetime | None = None
    remark: str | None = None


class BillCreate(BillBase):
    """手动创建账单 (不走 OCR)"""


class BillUpdate(BaseModel):
    bill_no: str | None = None
    bill_kind: BillKind | None = None
    bill_type: str | None = None
    booking_id: str | None = None
    seller_name: str | None = None
    seller_tax_no: str | None = None
    buyer_name: str | None = None
    buyer_tax_no: str | None = None
    currency: str | None = None
    total_amount: float | None = None
    tax_amount: float | None = None
    amount_excl_tax: float | None = None
    line_items: list[dict[str, Any]] | None = None
    status: BillStatus | None = None
    issued_at: datetime | None = None
    due_at: datetime | None = None
    paid_at: datetime | None = None
    payment_method: str | None = None
    payment_ref: str | None = None
    remark: str | None = None


class BillRead(BillBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: BillStatus
    matched_booking_id: str | None
    matched_at: datetime | None
    match_score: float | None
    payment_method: str | None
    payment_ref: str | None
    file_path: str | None
    file_name: str | None
    file_mime: str | None
    file_size: int
    ocr_text: str | None
    ocr_engine: str | None
    ocr_confidence: float | None
    ocr_error: str | None
    ocr_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BillListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bill_no: str
    bill_kind: BillKind
    bill_type: str
    status: BillStatus
    currency: str
    total_amount: float | None
    seller_name: str | None
    buyer_name: str | None
    booking_id: str | None
    matched_booking_id: str | None
    match_score: float | None
    payment_method: str | None
    file_name: str | None
    issued_at: datetime | None
    due_at: datetime | None
    paid_at: datetime | None
    created_at: datetime


class BillListResponse(BaseModel):
    items: list[BillListItem]
    total: int
    page: int
    page_size: int


class PayBillRequest(BaseModel):
    """回款登记"""

    payment_method: str = Field(..., description="bank_transfer / alipay / wechat / cash / cheque")
    payment_ref: str | None = None
    paid_at: datetime | None = None


class FinanceKPIResponse(BaseModel):
    receivable_total: float
    receivable_paid: float
    receivable_pending: float
    payable_total: float
    payable_paid: float
    payable_pending: float
    overdue_count: int
    by_carrier: dict[str, float]


class ReconcileResult(BaseModel):
    matched: int
    skipped: int
    results: list[dict[str, Any]] = Field(default_factory=list)
