"""SO Schemas"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.so import SOStatus


class SOBase(BaseModel):
    carrier: str | None = None
    so_number: str | None = None
    bl_number: str | None = None
    booking_number: str | None = None
    vessel_name: str | None = None
    voyage_no: str | None = None
    pol: str | None = None
    pod: str | None = None
    etd: datetime | None = None
    eta: datetime | None = None
    cut_off: datetime | None = None
    container_type: str | None = None
    container_count: int | None = None
    shipper: str | None = None
    consignee: str | None = None
    notify_party: str | None = None
    commodity: str | None = None
    extra_fields: dict[str, Any] = Field(default_factory=dict)


class SOCreate(SOBase):
    """上传/创建 SO - 必填文件路径,其他字段可由 OCR 填"""


class SOUpdate(SOBase):
    """用户修正字段后提交"""


class SORead(SOBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: SOStatus
    source: str
    source_email: str | None
    source_subject: str | None
    file_name: str
    file_size: int
    ocr_engine: str | None
    ocr_confidence: float | None
    ocr_error: str | None
    ocr_at: datetime | None
    booking_id: str | None
    created_at: datetime
    updated_at: datetime


class SOListItem(BaseModel):
    """列表用, 字段精简"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: SOStatus
    carrier: str | None
    so_number: str | None
    pol: str | None
    pod: str | None
    etd: datetime | None
    container_type: str | None
    container_count: int | None
    file_name: str
    created_at: datetime


class SOListResponse(BaseModel):
    items: list[SOListItem]
    total: int
    page: int
    page_size: int
