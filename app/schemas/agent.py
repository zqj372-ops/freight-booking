"""Agent Schemas"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AgentBase(BaseModel):
    name: str
    code: str | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    contact_wechat: str | None = None
    booking_email: str | None = None
    cc_emails: list[str] = Field(default_factory=list)
    service_routes: list[str] = Field(default_factory=list)
    notes: str | None = None
    is_active: bool = True


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    contact_wechat: str | None = None
    booking_email: str | None = None
    cc_emails: list[str] | None = None
    service_routes: list[str] | None = None
    notes: str | None = None
    is_active: bool | None = None


class AgentRead(AgentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
