"""Container schemas - v0.5"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ContainerStatusLiteral = Literal[
    "pending", "picked_up", "loaded", "in_transit", "discharged", "returned",
]


class ContainerCreate(BaseModel):
    """建柜, 通常系统自动 (shipment 创建时) 生成 1 个 TBD 柜"""

    shipment_id: str
    container_type: str = "40HQ"


class ContainerUpdate(BaseModel):
    """录入柜号/封条号/提柜/装船时间"""

    container_no: str | None = Field(None, min_length=4, max_length=32)
    seal_no: str | None = None
    pickup_location: str | None = None
    pickup_time: datetime | None = None
    loaded_time: datetime | None = None
    return_time: datetime | None = None
    pieces: int | None = Field(None, ge=0)
    gross_weight_kg: float | None = Field(None, ge=0)
    volume_cbm: float | None = Field(None, ge=0)


class ContainerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    shipment_id: str
    container_no: str | None
    seal_no: str | None
    container_type: str
    pickup_location: str | None
    pickup_time: datetime | None
    loaded_time: datetime | None
    return_time: datetime | None
    pieces: int | None
    gross_weight_kg: float | None
    volume_cbm: float | None
    status: str
    created_at: datetime
    updated_at: datetime
