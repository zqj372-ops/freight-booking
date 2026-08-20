"""BookingConfirmation schemas - v0.5"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


BookingConfirmationStatusLiteral = Literal[
    "unmatched", "matched_pending", "accepted", "superseded", "rejected", "duplicate",
]


class BookingConfirmationCreate(BaseModel):
    """人工录入或系统自动创建 (来自 SO 抽取)"""

    shipment_id: str
    booking_request_id: str | None = None
    document_id: str | None = None
    extraction_id: str | None = None

    carrier: str | None = None
    carrier_booking_no: str | None = None
    so_no: str | None = None
    bl_no: str | None = None
    vessel_name: str | None = None
    voyage_no: str | None = None
    pol: str | None = None
    pod: str | None = None
    etd: date | None = None
    eta: date | None = None
    cy_open_at: datetime | None = None
    si_cutoff_at: datetime | None = None
    vgm_cutoff_at: datetime | None = None
    cy_cutoff_at: datetime | None = None
    container_type: str | None = None
    container_count: int | None = None

    context: dict[str, Any] | None = None
    remark: str | None = None


class BookingConfirmationAccept(BaseModel):
    """接受 booking confirmation, 字段写入 Shipment"""

    reason: str = Field(..., min_length=5, description="接受原因, 必填")
    # 可选: 同时录入的实际值 (覆盖 confirmation 里的字段, 用于人工校正)
    overrides: dict[str, Any] | None = None


class BookingConfirmationReject(BaseModel):
    """拒绝 booking confirmation"""

    reason: str = Field(..., min_length=5)


class BookingConfirmationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    shipment_id: str
    booking_request_id: str | None
    document_id: str | None
    extraction_id: str | None

    carrier: str | None
    carrier_booking_no: str | None
    so_no: str | None
    bl_no: str | None
    vessel_name: str | None
    voyage_no: str | None
    pol: str | None
    pod: str | None
    etd: date | None
    eta: date | None
    cy_open_at: datetime | None
    si_cutoff_at: datetime | None
    vgm_cutoff_at: datetime | None
    cy_cutoff_at: datetime | None
    container_type: str | None
    container_count: int | None

    context: dict[str, Any] | None
    version: int
    is_current: bool
    supersedes_id: str | None
    status: str
    review_status: str

    accepted_at: datetime | None
    accepted_by: str | None
    accepted_by_name: str | None

    remark: str | None
    created_at: datetime
    updated_at: datetime
