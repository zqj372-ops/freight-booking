"""BookingRequest schemas - v0.5"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


BookingRequestStatusLiteral = Literal[
    "draft", "sent", "acknowledged", "confirmed", "rejected", "cancelled",
]


class BookingRequestCreate(BaseModel):
    """建订舱申请"""

    shipment_id: str
    partner_id: str
    requested_etd: date
    requested_pol: str = Field(..., min_length=3, max_length=64)
    requested_pod: str = Field(..., min_length=3, max_length=64)
    requested_container_type: str = Field("40HQ")
    requested_container_count: int = Field(1, ge=1)
    carrier_preference: str | None = None
    expected_response_by: datetime | None = None
    response_sla_hours: int | None = Field(None, ge=1, le=720)
    remark: str | None = None
    # supersedes_id 可选: 显式创建新版 (改 ETD 时) 时填, 默认 None
    supersedes_id: str | None = None


class BookingRequestUpdate(BaseModel):
    """修改 booking_request (只允许 draft 状态)"""

    requested_etd: date | None = None
    requested_pol: str | None = None
    requested_pod: str | None = None
    requested_container_type: str | None = None
    requested_container_count: int | None = None
    carrier_preference: str | None = None
    expected_response_by: datetime | None = None
    response_sla_hours: int | None = None
    remark: str | None = None


class BookingRequestSend(BaseModel):
    """发送订舱申请 (调 email service)"""

    template_code: str = Field("booking_request", description="邮件模板 code")
    to_emails: list[str] = Field(..., min_length=1)
    cc_emails: list[str] = Field(default_factory=list)
    dry_run: bool = Field(False, description="只渲染不真发, 用于预览")


class BookingRequestCancel(BaseModel):
    """取消订舱申请"""

    reason: str = Field(..., min_length=5)


class BookingRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    shipment_id: str
    partner_id: str
    booking_request_no: str
    request_version: int
    supersedes_id: str | None
    cargo_snapshot: dict[str, Any]
    requested_etd: date
    requested_pol: str
    requested_pod: str
    requested_container_type: str
    requested_container_count: int
    carrier_preference: str | None
    email_thread_id: str | None
    email_message_id: str | None
    status: str
    sent_at: datetime | None
    acknowledged_at: datetime | None
    confirmed_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    expected_response_by: datetime | None
    response_sla_hours: int | None
    remark: str | None
    created_at: datetime
    updated_at: datetime
