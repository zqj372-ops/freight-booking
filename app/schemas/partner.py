"""Partner schemas - v0.5"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


PartnerTypeLiteral = Literal[
    "customer", "carrier", "agent_l1", "agent_l2",
    "trucking", "warehouse", "customs_broker",
]


class PartnerBase(BaseModel):
    partner_type: PartnerTypeLiteral
    name: str = Field(..., min_length=1, max_length=255)
    short_code: str | None = Field(None, max_length=64)
    primary_email: EmailStr | None = None
    cc_emails: list[str] = Field(default_factory=list)
    contact_person: str | None = Field(None, max_length=64)
    contact_phone: str | None = Field(None, max_length=32)
    contact_wechat: str | None = Field(None, max_length=64)
    preferred_routes: list[str] = Field(default_factory=list)
    preferred_carriers: list[str] = Field(default_factory=list)
    response_sla_hours: int | None = Field(None, ge=1, le=720)
    default_template_id: str | None = None
    remark: str | None = None
    is_active: bool = True


class PartnerCreate(PartnerBase):
    pass


class PartnerUpdate(BaseModel):
    name: str | None = None
    short_code: str | None = None
    primary_email: EmailStr | None = None
    cc_emails: list[str] | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    contact_wechat: str | None = None
    preferred_routes: list[str] | None = None
    preferred_carriers: list[str] | None = None
    response_sla_hours: int | None = None
    default_template_id: str | None = None
    remark: str | None = None
    is_active: bool | None = None


class PartnerRead(PartnerBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    created_at: datetime
    updated_at: datetime
