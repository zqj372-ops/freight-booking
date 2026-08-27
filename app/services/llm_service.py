"""v0.6 LLM service (mock + 接口预留)

v0.6.1 决策: Mock LLM + 预留 interface
- 真实接 LLM (OpenAI/Claude/国内模型) 在 v0.6.2+
- mock 用关键词匹配 + 模板生成, 跟真 LLM 输出一致格式 (summary/confidence/sources)
- 接口: summarize_fetch_results / suggest_action / answer_question

后续接真 LLM 时, 只需要:
1. 加 LLM_PROVIDER=openai 环境变量
2. 实现 _call_openai / _call_qwen 等
3. 业务侧不需改
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any

from loguru import logger

# v0.6.1 决策: 走 mock
MOCK_MODEL_NAME = "mock-gpt-4o-mini"


@dataclass
class LlmSummary:
    """LLM 输出统一格式 (后续接真 LLM 保持一致)"""

    text: str
    confidence: float  # 0-1, mock 默认 0.85
    sources: list[str]  # 引用 (shipment_id/exception_id/email_id 等)
    model: str = MOCK_MODEL_NAME
    raw: dict[str, Any] | None = None  # LLM 原始响应 (审计用)


def _mock_confidence(seed: str) -> float:
    """基于 seed 生成稳定置信度 (0.7-0.95)"""
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return round(0.7 + (h % 250) / 1000.0, 3)


# ========== 摘要 fetch results (写入 ExceptionUpdate.ai_summary) ==========


def summarize_fetch_results(
    fetch_summaries: list[dict[str, Any]],
    exception_code: str,
) -> LlmSummary:
    """对一组 fetch 结果做中文摘要

    Args:
        fetch_summaries: [{"source": "carrier_website", "summary": "..."}, ...]
        exception_code: OperationalException.code, 辅助理解

    Returns:
        LlmSummary (text/confidence/sources/model)
    """
    if not fetch_summaries:
        return LlmSummary(
            text="无可用信息, 暂时无法判断异常进展",
            confidence=0.5,
            sources=[],
            raw={"reason": "no fetch results"},
        )

    # 简单 mock: 把 fetch_summaries 拼成一段中文
    parts = []
    sources = []
    progress_count = 0
    for fr in fetch_summaries:
        src = fr.get("source", "?")
        summ = fr.get("summary", "")
        progress = fr.get("progress_made", False)
        parts.append(f"[{src}] {summ}")
        sources.append(src)
        if progress:
            progress_count += 1

    if progress_count == 0:
        text = (
            f"针对 {exception_code} 异常, 已抓取 {len(fetch_summaries)} 个源, "
            f"暂无新进展。建议继续观察或人工跟进。"
        )
    else:
        text = (
            f"针对 {exception_code} 异常, 已抓取 {len(fetch_summaries)} 个源, "
            f"其中 {progress_count} 个源有进展: " + " | ".join(parts[:3])
        )

    seed = f"{exception_code}-" + "-".join(sources)
    return LlmSummary(
        text=text,
        confidence=_mock_confidence(seed),
        sources=sources,
        raw={"fetch_summaries": fetch_summaries, "mock": True},
    )


# ========== AI 建议: 可关闭/需关注 ==========


SUGGEST_CLOSE_TEMPLATES = [
    "船公司反馈已恢复正常, 建议关闭异常",
    "邮件显示客户已确认信息, 建议关闭异常",
    "截关时间已过, 异常已自动消化, 建议关闭",
]
SUGGEST_KEEP_TEMPLATES = [
    "船公司仍无明确回复, 建议继续跟进并升级处理",
    "客户尚未确认, 建议人工电话跟进",
    "信息仍不充分, 建议再观察 24h 后重新评估",
]


def suggest_action(
    exception_code: str,
    fetch_summaries: list[dict[str, Any]],
    has_recent_progress: bool,
) -> LlmSummary:
    """根据 fetch 结果给操作员建议: 可关闭 / 需关注

    v0.6.1 决策: AI 建议 + 人确认 (不自动 close)
    """
    if not fetch_summaries:
        text = "无任何抓取信息, 建议人工介入判断"
        confidence = 0.5
    elif has_recent_progress and len(fetch_summaries) >= 2:
        # 多源有进展 → 倾向 close
        template = random.choice(SUGGEST_CLOSE_TEMPLATES)
        text = f"{template} (基于 {len(fetch_summaries)} 个源)"
        confidence = 0.88
    elif has_recent_progress:
        template = random.choice(SUGGEST_KEEP_TEMPLATES)
        text = f"{template} (仅 1 个源有进展)"
        confidence = 0.72
    else:
        template = random.choice(SUGGEST_KEEP_TEMPLATES)
        text = f"{template} (0 源进展)"
        confidence = 0.65

    seed = f"suggest-{exception_code}-{has_recent_progress}-{len(fetch_summaries)}"
    return LlmSummary(
        text=text,
        confidence=confidence,
        sources=[fr.get("source", "?") for fr in fetch_summaries],
        raw={
            "exception_code": exception_code,
            "has_recent_progress": has_recent_progress,
            "fetch_count": len(fetch_summaries),
        },
    )


# ========== 全局 AI 问答 ==========


ANSWER_TEMPLATES = {
    "shipment_count": "当前共 {count} 个业务单, 其中 in_progress {in_progress}, completed {completed}",
    "exception_count": "当前共 {count} 个未关闭异常, critical {critical}, warning {warning}, info {info}",
    "forecast": "本周共 {count} 条预报, 配载率 {rate}%",
    "unknown": "已记录您的问题, 但 mock LLM 暂不支持该问题类型。v0.6.2 接真 LLM 后可回答。",
}


def answer_question(
    question: str,
    context: dict[str, Any] | None = None,
) -> LlmSummary:
    """全局 AI 问答 (任何问题, mock 走关键词匹配)

    Args:
        question: 用户问的问题
        context: 业务侧 context (e.g. {"shipment_count": 12, "exception_count": 3, ...})

    Returns:
        LlmSummary
    """
    ctx = context or {}
    q_lower = question.lower()

    # 简单关键词匹配
    if "shipment" in q_lower or "业务单" in question or "订舱" in question:
        key = "shipment_count"
    elif "异常" in question or "exception" in q_lower:
        key = "exception_count"
    elif "预报" in question or "forecast" in q_lower:
        key = "forecast"
    else:
        key = "unknown"

    template = ANSWER_TEMPLATES[key]
    try:
        text = template.format(**ctx)
    except KeyError as e:
        logger.warning(f"answer_question 缺少 context {e}, 用 unknown fallback")
        text = ANSWER_TEMPLATES["unknown"]

    return LlmSummary(
        text=text,
        confidence=0.8 if key != "unknown" else 0.4,
        sources=list(ctx.keys()) if ctx else [],
        raw={"question": question, "matched_key": key, "context": ctx},
    )


# ========== 跟真 LLM 切换示例 (v0.6.2 留) ==========


async def _call_real_llm(prompt: str, model: str = "gpt-4o-mini") -> dict[str, Any]:
    """调用真 LLM (v0.6.2+ 实现)

    TODO:
    1. 读 settings.llm_provider / settings.llm_api_key
    2. 调 OpenAI/Claude/Qwen SDK
    3. 返 {"text": "...", "usage": {...}, "model": "..."}
    """
    raise NotImplementedError(
        "v0.6.1 mock only, v0.6.2+ 接真 LLM (OpenAI/Claude/Qwen)"
    )
