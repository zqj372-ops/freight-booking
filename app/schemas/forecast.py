"""Forecast Pydantic schemas - v0.6 预报模块"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ForecastSourceLiteral = Literal[
    "sales", "customer_service", "shending", "subsidiary", "manual",
]
ForecastStatusLiteral = Literal[
    "forecasted", "confirmed", "allocated", "loaded", "cancelled",
]
ContainerTypeLiteral = Literal["20GP", "40GP", "40HQ", "45HQ", "20OT", "40OT", "20FR", "40FR"]


class ForecastCreate(BaseModel):
    """建预报单 (单条)

    最小化必填字段: customer_id + 航线 + ETD + 柜型 + 数量.
    source_ref 是上游单号, 可选但有则更准 (同源 UNIQUE 去重).
    """

    source: ForecastSourceLiteral = "manual"
    source_ref: str | None = Field(None, max_length=128)
    customer_id: str
    customer_name: str = Field(..., min_length=1, max_length=255)
    pol: str = Field(..., min_length=3, max_length=64)
    pod: str = Field(..., min_length=3, max_length=64)
    container_type: ContainerTypeLiteral = "40HQ"
    container_count: int = Field(1, ge=1, le=100)
    target_etd: date
    commodity: str | None = Field(None, max_length=255)
    weight_kg: float | None = Field(None, ge=0)
    volume_cbm: float | None = Field(None, ge=0)
    pieces: int | None = Field(None, ge=0)
    is_dangerous: bool = False
    notes: str | None = None
    source_metadata: dict[str, Any] | None = None


class ForecastBulkCreate(BaseModel):
    """批量建预报 (CSV 导入用)"""

    forecasts: list[ForecastCreate]
    dry_run: bool = Field(False, description="True = 仅 dedup 检测不入库, False = 真实导入")


class ForecastUpdate(BaseModel):
    """更新预报 (forecasts/allocated/loaded/cancelled 状态切换)"""

    status: ForecastStatusLiteral | None = None
    shipment_id: str | None = None
    notes: str | None = None
    reason: str = Field(..., min_length=3, description="更新原因, 写 audit log")


class ForecastRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    source: str
    source_ref: str | None
    content_fingerprint: str
    customer_id: str
    customer_name: str
    pol: str
    pod: str
    container_type: str
    container_count: int
    target_etd: date
    commodity: str | None
    weight_kg: float | None
    volume_cbm: float | None
    pieces: int | None
    is_dangerous: bool
    status: str
    shipment_id: str | None
    notes: str | None
    source_metadata: dict[str, Any] | None
    created_by_user_id: str | None
    created_by_user_name: str | None
    created_at: datetime
    updated_at: datetime


class ForecastDedupCheck(BaseModel):
    """dedup 检测结果 (返回相似/重复的 forecasts 给用户决策)"""

    fingerprint: str
    match_count: int
    match_ids: list[str]
    new_forecast_id: str | None = None
    action: Literal["create_new", "merge_into_existing", "needs_human"]
    note: str = ""


class ForecastBulkCreateResult(BaseModel):
    """批量导入结果"""

    created: int
    duplicates: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
    details: list[ForecastDedupCheck] = Field(default_factory=list)


class ForecastWeeklyRow(BaseModel):
    """周汇总一行 (按 pol/pod × customer_id 聚合)"""

    pol: str
    pod: str
    customer_id: str
    customer_name: str
    total_count: int = Field(..., description="所有 forecast 柜数总和")
    confirmed_count: int = Field(..., description=">= 2 源确认的柜数")
    allocated_count: int = Field(..., description="已配载的柜数 (有 shipment_id)")
    pending_count: int = Field(..., description="待配载")
    forecast_ids: list[str] = Field(..., description="本聚合包含的 forecast id")
    source_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="按 source 拆分的柜数, e.g. {'sales': 3, 'customer_service': 1}",
    )


class ForecastWeeklySummary(BaseModel):
    """整周汇总 (多行)"""

    week_start: date
    week_end: date
    rows: list[ForecastWeeklyRow]
    total_forecast_count: int
    total_allocated_count: int
    cut_off_alerts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="截单预警: [{forecast_id, cy_cutoff_at, days_remaining}]",
    )


class ForecastAllocateRequest(BaseModel):
    """forecast 配载 (关联到 Shipment)"""

    shipment_id: str = Field(..., description="已存在的 Shipment (v0.5 shipment.id)")


class ForecastCancelRequest(BaseModel):
    """取消预报"""

    reason: str = Field(..., min_length=3, max_length=500)


class ForecastCsvImportRequest(BaseModel):
    """CSV 导入请求 body (含 dry_run 开关)"""

    dry_run: bool = Field(False, description="True = 仅 dedup 预判, False = 真实导入")
    source: ForecastSourceLiteral = "manual"
    source_ref_prefix: str | None = Field(None, description="source_ref 自动加前缀, 防止同 file 多行撞 UNIQUE")
