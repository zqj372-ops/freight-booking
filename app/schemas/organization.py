"""Organization schemas - v0.5"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OrganizationBase(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    display_name: str = Field(..., min_length=1, max_length=255)
    job_no_prefix: str = Field(default="FB", min_length=1, max_length=8)
    job_no_date_fmt: Literal["YYYY", "YYYYMM", "YYYYMMDD"] = "YYYYMMDD"
    job_no_seq_digits: int = Field(default=4, ge=2, le=8)
    job_no_reset_policy: Literal["daily", "monthly", "never"] = "daily"


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    display_name: str | None = None
    job_no_prefix: str | None = None
    job_no_date_fmt: Literal["YYYY", "YYYYMM", "YYYYMMDD"] | None = None
    job_no_seq_digits: int | None = None
    job_no_reset_policy: Literal["daily", "monthly", "never"] | None = None


class OrganizationRead(OrganizationBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime
