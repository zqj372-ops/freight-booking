"""AuditLog schemas - v0.5"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AuditActionLiteral = Literal[
    "create", "update", "delete", "stage_change", "cancel",
    "accept", "reject", "send", "match", "upload", "ocr_done",
    "resolve", "auto_close", "record",
]

AuditActorTypeLiteral = Literal["user", "system", "scheduled_job", "api"]


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    entity_type: str
    entity_id: str
    action: str
    actor_type: str
    actor_user_id: str | None
    actor_user_name: str | None
    actor_job_name: str | None
    field_changes: dict[str, Any] | None
    context: dict[str, Any] | None
    reason: str | None
    created_at: datetime


class AuditLogListQuery(BaseModel):
    entity_type: str | None = None
    entity_id: str | None = None
    action: AuditActionLiteral | None = None
    actor_user_id: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
