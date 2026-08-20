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


class ShipmentEventsUpdate(BaseModel):
    """v0.5 1.5.3: 11 触发字段 + fire 17 SLA trigger

    设置触发字段 → 后端自动建对应 SLA task.
    - so_received_at → fire SO_RECEIVED (建 send_so_to_trucker 2h task)
    - si_info_ready_at → fire SI_INFO_READY (建 send_si 2h task)
    - bl_draft_received_at → fire BL_DRAFT_RECEIVED (建 review_bl_draft 30min task)
    - sealed_at → fire SEALED (建 send_customs_docs 2h task)
    - empty_return_due_at → fire EMPTY_RETURN_DUE (建 return_empty 提醒 task)
    - 其他 6 个字段 (booking_request_sent_at / cy_open_at / si_cutoff_at / vgm_cutoff_at /
      cy_cutoff_at / last_updated_at): 仅存值, 不 fire trigger
    """

    booking_request_sent_at: datetime | None = None
    so_received_at: datetime | None = None
    si_info_ready_at: datetime | None = None
    bl_draft_received_at: datetime | None = None
    sealed_at: datetime | None = None
    cy_open_at: datetime | None = None
    si_cutoff_at: datetime | None = None
    vgm_cutoff_at: datetime | None = None
    cy_cutoff_at: datetime | None = None
    empty_return_due_at: datetime | None = None
    last_updated_at: datetime | None = None

    reason: str | None = Field(None, min_length=5)


# v0.5 1.5.4: 主列表 12 字段 + dashboard + document-checklist
class ShipmentListItem(BaseModel):
    """主列表 12 字段 (1.5.4 final)"""

    id: str
    job_no: str
    route_summary: str  # CNSZX → CAVAN 1×40HQ
    carrier_partner: str  # COSCO 华南一级代理
    vessel_voyage: str  # COSCO SHIPPING... 082E
    current_etd: str | None
    current_eta: str | None
    business_phase: int
    business_phase_label: str
    business_phase_color: str
    next_action: str
    next_due_at: str | None
    countdown_hours: float | None
    next_action_priority: str  # urgent/important/normal/waiting_external/none
    operator_user_name: str | None
    exception_label: str  # "一般/重要/紧急/—"
    progress: float
    last_updated_at: str | None


class DashboardTaskItem(BaseModel):
    task_id: str
    title: str
    due_at: str | None
    job_no: str | None
    pol: str | None
    pod: str | None
    shipment_id: str


class DashboardStats(BaseModel):
    """4 卡片 (主列表顶部)"""

    overdue_tasks: int
    due_today: int
    awaiting_so: int
    arriving_within_7d: int
    overdue_tasks_top: list[DashboardTaskItem] = []
    due_today_top: list[DashboardTaskItem] = []


class DocumentChecklistItem(BaseModel):
    code: str
    label: str
    required: bool
    status: str  # completed/partial/missing/not_applicable
    count: int
    expected: int
    latest_doc_id: str | None
    latest_received_at: str | None


class DocumentChecklist(BaseModel):
    shipment_id: str
    items: list[DocumentChecklistItem]
    total_required: int
    total_completed: int
    completion: float
