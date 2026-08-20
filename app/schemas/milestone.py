"""Milestone + Task + OperationalException schemas - v0.5"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MilestoneCodeLiteral = Literal[
    "booking_request_sent", "booking_request_acknowledged",
    "booking_confirmation_received", "booking_confirmation_accepted",
    "booking_rejected", "empty_release_available",
    "container_picked_up", "container_gated_in", "container_loaded",
    "si_submitted", "vgm_submitted", "customs_cleared",
    "si_cutoff_passed", "vgm_cutoff_passed", "cy_cutoff_passed",
    "gate_in", "departed", "arrived_at_pol", "in_transit",
    "arrived_at_pod", "customs_cleared_at_pod", "container_discharged",
    "delivered", "empty_returned",
]


class MilestoneCreate(BaseModel):
    code: MilestoneCodeLiteral
    occurred_at: datetime
    location: str | None = None
    vessel_name: str | None = None
    voyage_no: str | None = None
    container_no: str | None = None
    source: Literal["auto", "manual", "email", "api"] = "manual"
    source_ref: str | None = None
    remark: str | None = None


class MilestoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    shipment_id: str
    code: str
    occurred_at: datetime
    recorded_at: datetime
    source: str
    source_ref: str | None
    location: str | None
    vessel_name: str | None
    voyage_no: str | None
    container_no: str | None
    remark: str | None
    corrected_at: datetime | None
    corrected_by: str | None
    corrected_milestone_id: str | None
    created_at: datetime
    updated_at: datetime


# === Task ===
TaskCodeLiteral = Literal[
    "confirm_so", "confirm_booking", "contact_supplier",
    "arrange_pickup", "record_container_no", "record_seal_no",
    "submit_si", "submit_vgm", "confirm_cargo_ready",
    "confirm_loaded", "handle_exception",
]
TaskStatusLiteral = Literal["pending", "in_progress", "done", "cancelled"]


class TaskCreate(BaseModel):
    code: TaskCodeLiteral
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime | None = None
    assignee_user_id: str | None = None
    assignee_user_name: str | None = None
    auto_close_on: MilestoneCodeLiteral | None = None
    context: dict[str, Any] | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    due_at: datetime | None = None
    assignee_user_id: str | None = None
    assignee_user_name: str | None = None
    status: TaskStatusLiteral | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    shipment_id: str
    code: str
    title: str
    description: str | None
    due_at: datetime | None
    assignee_user_id: str | None
    assignee_user_name: str | None
    status: str
    completed_at: datetime | None
    completed_by: str | None
    completed_by_name: str | None
    auto_close_on: str | None
    context: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


# === OperationalException ===
ExceptionCodeLiteral = Literal[
    "booking_response_overdue", "booking_rejected", "so_mismatch",
    "schedule_changed", "port_changed", "carrier_changed",
    "container_rolled", "cutoff_approaching", "cutoff_passed",
    "si_overdue", "vgm_overdue", "missing_container_no", "missing_seal_no",
    "email_send_failed", "email_parse_failed",
]
ExceptionSeverityLiteral = Literal["info", "warning", "critical"]
ExceptionStatusLiteral = Literal["open", "resolved", "auto_closed"]


class OpExCreate(BaseModel):
    code: ExceptionCodeLiteral
    severity: ExceptionSeverityLiteral = "warning"
    context: dict[str, Any] | None = None
    related_milestone_id: str | None = None
    related_task_id: str | None = None


class OpExResolve(BaseModel):
    resolution: str = Field(..., min_length=5, description="处理说明, 必填 >= 5 字符")


class OpExRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    shipment_id: str
    code: str
    severity: str
    status: str
    detected_at: datetime
    detected_by: str
    resolved_at: datetime | None
    resolved_by: str | None
    resolved_by_name: str | None
    resolution: str | None
    related_milestone_id: str | None
    related_task_id: str | None
    context: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
