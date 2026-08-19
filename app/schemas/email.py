"""Email Schemas"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EmailTemplateBase(BaseModel):
    code: str
    name: str
    subject: str
    body: str
    is_active: bool = True


class EmailTemplateCreate(EmailTemplateBase):
    pass


class EmailTemplateUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    body: str | None = None
    is_active: bool | None = None


class EmailTemplateRead(EmailTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class EmailLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_code: str | None
    to_emails: list[str]
    cc_emails: list[str]
    subject: str
    status: str
    sent_at: datetime | None
    error: str | None
    retry_count: int
    booking_id: str | None
    so_id: str | None
    context: dict[str, Any]
    created_at: datetime


class EmailSendRequest(BaseModel):
    """手动发送邮件请求"""

    template_code: str | None = None
    to_emails: list[EmailStr] = Field(min_length=1)
    cc_emails: list[EmailStr] = Field(default_factory=list)
    subject: str
    body: str
    attachments: list[str] = Field(default_factory=list)
    booking_id: str | None = None
    so_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
