"""Email Ingestion Schemas"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.email_ingestion import IngestionSource, IngestionStatus


class EmailIngestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: IngestionSource
    mailbox: str
    status: IngestionStatus
    started_at: datetime
    finished_at: datetime | None
    total_fetched: int
    new_count: int
    skip_count: int
    error_count: int
    error: str | None
    so_ids: list[str]
    skipped_message_ids: list[str]
    created_at: datetime


class IngestionResultRead(BaseModel):
    """手动拉取结果"""

    ingestion_id: str
    source: IngestionSource
    total_fetched: int
    new_count: int
    skip_count: int
    error_count: int
    error: str | None
    so_ids: list[str]


class ProcessedEmailRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    message_id: str
    from_addr: str | None
    subject: str | None
    received_at: datetime | None
    source: IngestionSource
    so_id: str | None
    processed_at: datetime
