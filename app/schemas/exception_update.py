"""v0.6 异常 AI 跟进 Pydantic schemas"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ExceptionUpdateTypeLiteral = Literal[
    "ai_fetch", "ai_summary", "user_note", "status_change", "ai_suggestion", "user_response",
]
ExceptionUpdateSourceLiteral = Literal[
    "carrier_website", "email", "wechat", "user", "ai_inference",
]
ExceptionFetchJobStatusLiteral = Literal["pending", "running", "done", "failed", "cancelled"]


class ExceptionUpdateCreate(BaseModel):
    """用户手动加 update (备注/采纳/拒绝 AI 建议)"""

    update_type: ExceptionUpdateTypeLiteral = "user_note"
    summary: str = Field(..., min_length=1, max_length=2000)
    # 用户响应 (采纳 AI 建议时)
    accept_ai_suggestion: bool = Field(False, description="True = 采纳 AI 建议并 close 异常")


class ExceptionUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    exception_id: str
    update_type: str
    source: str
    summary: str
    raw_data: dict[str, Any] | None
    ai_model: str | None
    ai_confidence: float | None
    created_by_type: str
    created_by_user_id: str | None
    created_by_user_name: str | None
    created_at: datetime


class ExceptionFetchJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    exception_id: str
    status: str
    source: str
    next_run_at: datetime
    last_run_at: datetime | None
    last_error: str | None
    run_count: int
    max_runs: int
    created_at: datetime


class ExceptionTimeline(BaseModel):
    """异常详情页 timeline 整体响应"""

    exception_id: str
    shipment_id: str
    code: str
    severity: str
    status: str
    detected_at: datetime
    resolved_at: datetime | None
    resolution: str | None
    updates: list[ExceptionUpdateRead] = Field(default_factory=list)
    fetch_jobs: list[ExceptionFetchJobRead] = Field(default_factory=list)
    # AI 给操作员的最新建议 (可关闭? 需关注?)
    latest_ai_suggestion: str | None = None
    latest_ai_confidence: float | None = None


class ExceptionAiQuestionRequest(BaseModel):
    """全局 AI 问答 (任何问题)"""

    question: str = Field(..., min_length=1, max_length=1000)
    # 可选 context (e.g. shipment_id 限定范围)
    shipment_id: str | None = None
    exception_id: str | None = None


class ExceptionAiAnswer(BaseModel):
    """AI 问答响应"""

    question: str
    answer: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    sources: list[str] = Field(default_factory=list, description="AI 引用的数据源 (shipment_id, exception_id 等)")
    model: str = Field(default="mock-gpt-4o-mini", description="使用的 LLM 模型")


class ExceptionFetchNowRequest(BaseModel):
    """立即触发 AI 跟进 (跳过调度)"""

    sources: list[ExceptionUpdateSourceLiteral] | None = Field(
        None, description="指定抓取源, None=全部 (carrier/email)",
    )
