"""Tracking Schemas"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.tracking import TrackingSource, TrackingStatus


class TrackingEventBase(BaseModel):
    status: TrackingStatus
    occurred_at: datetime
    location: str | None = None
    vessel_name: str | None = None
    voyage_no: str | None = None
    container_no: str | None = None
    remark: str | None = None


class TrackingEventCreate(TrackingEventBase):
    source: TrackingSource = TrackingSource.MANUAL


class TrackingEventRead(TrackingEventBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    booking_id: str
    source: TrackingSource
    created_at: datetime


class KanbanColumn(BaseModel):
    status: TrackingStatus
    label: str
    items: list[dict] = Field(default_factory=list)
    count: int = 0


class KanbanResponse(BaseModel):
    columns: list[KanbanColumn]
    total: int
