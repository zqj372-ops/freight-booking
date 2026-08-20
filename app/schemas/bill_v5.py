"""Bill v0.5 schemas"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


BillTypeLiteral = Literal["receivable", "payable"]
BillKindLiteral = Literal[
    "vat_special", "vat_normal", "vat_electronic",
    "freight_invoice", "ocean_freight", "detention", "demurrage", "other",
]
BillStatusLiteral = Literal[
    "uploaded", "ocr_processing", "ocr_done", "ocr_failed",
    "confirmed", "disputed", "paid",
]


class BillV5Base(BaseModel):
    bill_no: str = Field(..., min_length=1, max_length=64)
    bill_type: BillTypeLiteral = "receivable"
    bill_kind: BillKindLiteral = "other"
    shipment_id: str | None = None
    seller_name: str | None = None
    buyer_name: str | None = None
    currency: str = Field("CNY", min_length=1, max_length=8)
    total_amount: float | None = Field(None, ge=0)
    tax_amount: float | None = Field(None, ge=0)
    amount_excl_tax: float | None = Field(None, ge=0)
    due_at: datetime | None = None
    remark: str | None = None


class BillV5Create(BillV5Base):
    pass


class BillV5Update(BaseModel):
    """修改 Bill (部分字段)"""

    bill_type: BillTypeLiteral | None = None
    bill_kind: BillKindLiteral | None = None
    shipment_id: str | None = None
    seller_name: str | None = None
    buyer_name: str | None = None
    total_amount: float | None = Field(None, ge=0)
    tax_amount: float | None = Field(None, ge=0)
    amount_excl_tax: float | None = Field(None, ge=0)
    due_at: datetime | None = None
    remark: str | None = None


class BillV5Read(BillV5Base):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    status: str
    matched_shipment_id: str | None
    matched_at: datetime | None
    match_score: float | None
    payment_method: str | None
    payment_ref: str | None
    payment_proof_status: str | None
    payment_proof_uploaded_at: datetime | None
    issued_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BillStatusTransition(BaseModel):
    """Bill 状态机转换 (7 态)"""

    to: BillStatusLiteral
    reason: str = Field(..., min_length=5)
