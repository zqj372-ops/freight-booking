"""Booking Schemas"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.booking import BookingStatus


class BookingBase(BaseModel):
    carrier: str
    pol: str
    pod: str
    etd: datetime | None = None
    eta: datetime | None = None
    cut_off: datetime | None = None
    container_type: str = "40HQ"
    container_count: int = 1
    commodity: str | None = None
    weight_kg: float | None = None
    volume_cbm: float | None = None
    customer_name: str | None = None
    customer_ref: str | None = None
    agent_id: str | None = None
    remark: str | None = None


class BookingCreate(BookingBase):
    booking_no: str | None = None
    """留空自动生成"""
    status: BookingStatus = BookingStatus.DRAFT


class BookingUpdate(BaseModel):
    status: BookingStatus | None = None
    etd: datetime | None = None
    eta: datetime | None = None
    cut_off: datetime | None = None
    commodity: str | None = None
    weight_kg: float | None = None
    volume_cbm: float | None = None
    customer_name: str | None = None
    customer_ref: str | None = None
    agent_id: str | None = None
    remark: str | None = None


class BookingRead(BookingBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    booking_no: str
    status: BookingStatus
    created_at: datetime
    updated_at: datetime


class BookingListResponse(BaseModel):
    items: list[BookingRead]
    total: int
    page: int
    page_size: int
