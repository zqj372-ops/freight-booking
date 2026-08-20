"""EmailThread + EmailMessage schemas - v0.5 (与 v0.4 EmailLog schema 区分)"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EmailDirectionLiteral = Literal["inbound", "outbound"]
EmailStatusLiteral = Literal[
    "draft", "queued", "sent", "failed", "received", "processing", "processed", "ignored",
]
EmailThreadStatusLiteral = Literal["active", "closed", "spam"]


class EmailMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    thread_id: str
    direction: str
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    from_addr: str
    to_addrs: list[str]
    cc_addrs: list[str]
    subject: str
    body_text: str | None
    body_html: str | None
    received_at: datetime | None
    sent_at: datetime | None
    status: str
    error: str | None
    retry_count: int
    source: str
    raw_eml_path: str | None
    matched_shipment_id: str | None
    matched_booking_request_id: str | None
    match_confidence: float | None
    created_at: datetime
    updated_at: datetime


class EmailThreadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    subject: str
    subject_prefix: str | None
    shipment_id: str | None
    booking_request_id: str | None
    partner_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class EmailThreadWithMessages(EmailThreadRead):
    messages: list[EmailMessageRead] = Field(default_factory=list)
