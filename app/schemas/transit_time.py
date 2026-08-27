"""v0.6.3 头程时效 Pydantic schemas"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EtaUpdateSourceLiteral = Literal["manual", "document", "carrier_api", "system"]
EtaUpdateReasonLiteral = Literal[
    "initial", "carrier_revise", "port_delay", "weather", "vessel_delay", "documentation", "rolled", "other",
]


class EtaUpdateRequest(BaseModel):
    """操作员/系统更新 ETA"""

    new_eta: date
    reason: EtaUpdateReasonLiteral = "other"
    change_reason: str | None = Field(None, max_length=500)
    source: EtaUpdateSourceLiteral = "manual"
    related_document_id: str | None = None


class EtaUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_id: str
    old_eta: date | None
    new_eta: date
    delta_days: int
    source: str
    reason: str
    change_reason: str | None
    related_document_id: str | None
    updated_by_user_id: str | None
    updated_by_user_name: str | None
    triggered_exception_id: str | None
    created_at: datetime


class TransitOverview(BaseModel):
    """头程看板: 1 个 shipment 的 ETA 状态总览"""

    shipment_id: str
    job_no: str
    pol: str
    pod: str
    stage: str
    etd: date | None
    eta: date | None
    current_carrier: str | None
    # 状态分类
    status: str  # not_scheduled / scheduled / departed_in_transit / arrived / delayed / delivered
    # 延误信息
    days_to_eta: int | None  # 距 ETA 天数 (负数 = 已过)
    is_delayed: bool
    delay_days: int
    # 关键节点
    has_departed: bool
    has_arrived: bool
    has_discharged: bool
    has_delivered: bool
    # 最新 ETA 变更
    latest_eta_update: EtaUpdateRead | None
    # 未关闭异常数
    open_exception_count: int


class TransitBoard(BaseModel):
    """头程看板整体响应"""

    total: int
    by_status: dict[str, int]
    in_transit: list[TransitOverview]
    delayed: list[TransitOverview]
    upcoming_eta_7d: list[TransitOverview]
    upcoming_eta_1d: list[TransitOverview]


class EtaApproachingAlert(BaseModel):
    """ETA 临近提醒 (单条)"""

    shipment_id: str
    job_no: str
    eta: date
    days_left: int  # 距 ETA 剩余天数
    current_stage: str
    has_discharged: bool
    has_delivered: bool
