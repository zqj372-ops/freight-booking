"""Shipment schemas - v0.5"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ShipmentStageLiteral = Literal[
    "draft", "booking_in_progress", "awaiting_confirmation",
    "booked", "container_operation", "documentation",
    "departed", "completed", "cancelled",
]


class ShipmentBase(BaseModel):
    customer_partner_id: str | None = None
    customer_ref: str | None = None
    customer_name: str | None = None
    pol: str = Field(..., min_length=3, max_length=64, description="Port of Loading")
    pod: str = Field(..., min_length=3, max_length=64, description="Port of Discharge")
    final_destination: str | None = None
    target_etd: date
    commodity: str = Field(..., min_length=1)
    hs_code: str | None = None
    pieces: int | None = Field(None, ge=0)
    weight_kg: float | None = Field(None, ge=0)
    volume_cbm: float | None = Field(None, ge=0)
    is_dangerous: bool = False
    is_oversize: bool = False
    container_count: int = Field(1, ge=1, le=1, description="v0.5 强制 1 柜")
    current_partner_id: str | None = None
    current_carrier: str | None = None
    remark: str | None = None


class ShipmentCreate(ShipmentBase):
    """建业务单必填"""

    operator_user_id: str | None = None
    operator_user_name: str | None = None


class ShipmentUpdate(BaseModel):
    """修改业务单 - 部分字段"""

    customer_partner_id: str | None = None
    customer_ref: str | None = None
    final_destination: str | None = None
    target_etd: date | None = None
    etd: date | None = None
    eta: date | None = None
    carrier_booking_no: str | None = None
    so_no: str | None = None
    bl_no: str | None = None
    hs_code: str | None = None
    pieces: int | None = None
    weight_kg: float | None = None
    volume_cbm: float | None = None
    is_dangerous: bool | None = None
    is_oversize: bool | None = None
    current_partner_id: str | None = None
    current_carrier: str | None = None
    operator_user_id: str | None = None
    operator_user_name: str | None = None
    remark: str | None = None


class ShipmentRead(ShipmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    job_no: str
    legacy_job_no: str | None
    stage: str
    cancellation_reason: str | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    etd: date | None
    eta: date | None
    carrier_booking_no: str | None
    so_no: str | None
    bl_no: str | None
    operator_user_id: str | None
    operator_user_name: str | None
    sales_user_id: str | None
    sales_user_name: str | None
    rate_reference: str | None
    rate_valid_until: date | None
    # v0.5 1.5 新增触发字段
    booking_request_sent_at: datetime | None
    so_received_at: datetime | None
    si_info_ready_at: datetime | None
    bl_draft_received_at: datetime | None
    sealed_at: datetime | None
    cy_open_at: datetime | None
    si_cutoff_at: datetime | None
    vgm_cutoff_at: datetime | None
    cy_cutoff_at: datetime | None
    empty_return_due_at: datetime | None
    last_updated_at: datetime | None
    # v0.5 1.5.2: 5 类备注
    booking_remark: str | None
    bl_remark: str | None
    customs_remark: str | None
    pod_remark: str | None
    finance_remark: str | None
    # v0.5 1.5.2: 7 个状态字段
    customs_status: str | None
    inspection_status: str | None
    rolled_status: str | None
    payment_request_status: str | None
    payment_proof_status: str | None
    empty_return_status: str | None
    bl_process_status: str | None
    customs_released_at: datetime | None
    customs_released_by: str | None
    inspection_received_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ShipmentListQuery(BaseModel):
    stage: ShipmentStageLiteral | None = None
    customer_partner_id: str | None = None
    current_partner_id: str | None = None
    pol: str | None = None
    pod: str | None = None
    search: str | None = Field(None, description="job_no/customer_ref/legacy_job_no 模糊")
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


class ShipmentStageChange(BaseModel):
    """手动调整 stage (留 audit log + reason)"""

    stage: ShipmentStageLiteral
    reason: str = Field(..., min_length=5, description="调整原因, 必填 >= 5 字符")


# v0.5 1.5.2: 7 个状态 enum + 5 类备注
CustomsStatusLiteral = Literal["pending", "submitting", "released", "rejected", "inspecting"]
InspectionStatusLiteral = Literal["not_received", "received", "handling", "completed"]
RolledStatusLiteral = Literal["not_happened", "suspected", "confirmed", "reallocated", "closed"]
PaymentRequestStatusLiteral = Literal["not_requested", "requested", "approved", "paid"]
PaymentProofStatusLiteral = Literal["not_provided", "provided", "confirmed"]
EmptyReturnStatusLiteral = Literal["not_scheduled", "scheduled", "returned", "overdue", "abnormal"]
BlProcessStatusLiteral = Literal["not_started", "draft_received", "revising", "confirmed", "abnormal"]


class ShipmentStatusUpdate(BaseModel):
    """v0.5 1.5.2: 状态变更 (customs/inspection/rolled/payment_request/payment_proof/empty_return/bl_process 任一)

    request body 只传需要改的字段, 没传的不变.
    """

    customs_status: CustomsStatusLiteral | None = None
    inspection_status: InspectionStatusLiteral | None = None
    rolled_status: RolledStatusLiteral | None = None
    payment_request_status: PaymentRequestStatusLiteral | None = None
    payment_proof_status: PaymentProofStatusLiteral | None = None
    empty_return_status: EmptyReturnStatusLiteral | None = None
    bl_process_status: BlProcessStatusLiteral | None = None

    # 5 类备注
    booking_remark: str | None = None
    bl_remark: str | None = None
    customs_remark: str | None = None
    pod_remark: str | None = None
    finance_remark: str | None = None

    # 可选 reason (留 audit)
    reason: str | None = Field(None, min_length=5)
