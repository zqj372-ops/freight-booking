"""v0.6.2 清单复核 Pydantic schemas"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ChecklistReviewTypeLiteral = Literal["pre_load", "pre_cutoff", "pre_departure", "random"]
ChecklistReviewStatusLiteral = Literal["draft", "completed", "signed_off", "auto_closed"]
ChecklistItemCategoryLiteral = Literal["container", "declaration", "hs_code", "cutoff_doc"]
ChecklistItemCodeLiteral = Literal[
    "container_no_missing", "seal_no_missing", "container_type_mismatch",
    "container_count_mismatch",
    "pieces_mismatch", "weight_mismatch", "volume_mismatch",
    "hs_code_mismatch", "dangerous_goods_flag_missing", "oversize_goods_flag_missing",
    "si_missing", "vgm_missing", "ci_missing", "pl_missing",
]
ChecklistSeverityLiteral = Literal["pass", "warning", "critical"]


class ChecklistReviewCreate(BaseModel):
    """启动一次复核"""

    review_type: ChecklistReviewTypeLiteral = "random"
    trigger_reason: str | None = Field(None, max_length=500, description="触发原因")
    note: str | None = Field(None, max_length=2000)


class ChecklistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    review_id: str
    code: str
    category: str
    label: str
    expected_value: str | None
    actual_value: str | None
    match: bool
    severity: str
    delta: float | None
    delta_pct: float | None
    related_document_id: str | None
    related_container_id: str | None
    note: str | None
    acknowledged_by_user_id: str | None
    acknowledged_at: datetime | None
    created_at: datetime


class ChecklistReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_id: str
    review_type: str
    status: str
    reviewed_at: datetime | None
    signed_off_at: datetime | None
    reviewed_by_user_id: str | None
    reviewed_by_user_name: str | None
    total_items: int
    passed_items: int
    warning_items: int
    critical_items: int
    overall_severity: str
    trigger_reason: str | None
    related_exception_ids: list[str] | None
    note: str | None
    items: list[ChecklistItemRead] = Field(default_factory=list)
    created_at: datetime


class ChecklistReviewListItem(BaseModel):
    """列表用 (不含 items)"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_id: str
    review_type: str
    status: str
    reviewed_at: datetime | None
    signed_off_at: datetime | None
    total_items: int
    passed_items: int
    warning_items: int
    critical_items: int
    overall_severity: str
    created_at: datetime


class ChecklistAcknowledgeRequest(BaseModel):
    """操作员对某复核项确认 (warning 强制 pass)"""

    note: str | None = Field(None, max_length=500)


class ChecklistSignoffRequest(BaseModel):
    """签收整个复核"""

    note: str | None = Field(None, max_length=500)
