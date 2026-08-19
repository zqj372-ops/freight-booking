"""SO 字段解析 - 从 OCR 文本抽取船公司/航线/柜型等

MVP 策略:
- 先用通用正则 + 关键词定位
- 再按船公司 (carrier) 加载模板规则覆盖
- 解析失败的字段保持 None, 让用户在前端手动补
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


# 通用正则
RE_SO_NUMBER = re.compile(r"(?:S/O|SO|Booking\s*No|BK)\s*[:#]?\s*([A-Z0-9\-]{6,})", re.I)
RE_BL_NUMBER = re.compile(r"(?:B/L|BL|Bill\s*of\s*Lading)\s*(?:No\.?)?\s*[:#]?\s*([A-Z0-9\-]{6,})", re.I)
RE_VESSEL = re.compile(r"(?:Vessel|Ship)\s*[:：]?\s*([A-Z\s\.\-]+?)(?:\s*V\.\d+|\n|$)", re.I)
RE_VOYAGE = re.compile(r"(?:Voy(?:age)?\.?|V\.\s*)\s*[:：]?\s*(\d+[A-Z]?)", re.I)
RE_CONTAINER_TYPE = re.compile(r"\b(20GP|40GP|40HQ|45HQ|20RF|40RF|20OT|40OT|20FR|40FR)\b", re.I)
RE_CONTAINER_COUNT = re.compile(r"(\d+)\s*[xX×]\s*(?:20GP|40GP|40HQ|45HQ|20RF|40RF|20OT|40OT|20FR|40FR)", re.I)
RE_PORT = re.compile(
    r"(?:Port\s*of\s*Loading|POL)\s*[:：]?\s*([A-Za-z][^\n]+?)(?=\s*(?:\n|Port\s*of\s*Discharge|POD|Final|ETD|Place\s*of|$))",
    re.I,
)
RE_POD = re.compile(
    r"(?:Port\s*of\s*Discharge|POD|Place\s*of\s*Delivery)\s*[:：]?\s*([A-Za-z][^\n]+?)(?=\s*(?:\n|Final|ETA|Place\s*of|$))",
    re.I,
)
RE_DATE = re.compile(r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})")
RE_DATE2 = re.compile(r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})")

CARRIERS = [
    "MAERSK", "CMA CGM", "MSC", "COSCO", "EVERGREEN", "HAPAG-LLOYD",
    "ONE", "YANG MING", "HMM", "ZIM", "OOCL", "WANHAI", "PIL",
    "COSCO SHIPPING", "上海中远海运", "东方海外", "长荣", "阳明",
]

CARRIER_PATTERNS = {
    "MAERSK": re.compile(r"maersk", re.I),
    "MSC": re.compile(r"\bmsc\b", re.I),
    "COSCO": re.compile(r"cosco", re.I),
    "CMA CGM": re.compile(r"cma\s*cgm", re.I),
    "EVERGREEN": re.compile(r"evergreen", re.I),
    "HAPAG-LLOYD": re.compile(r"hapag", re.I),
    "ONE": re.compile(r"\bone\b", re.I),
    "YANG MING": re.compile(r"yang\s*ming", re.I),
    "HMM": re.compile(r"\bhmm\b", re.I),
    "ZIM": re.compile(r"\bzim\b", re.I),
    "OOCL": re.compile(r"oocl", re.I),
    "PIL": re.compile(r"\bpil\b", re.I),
}


def _detect_carrier(text: str) -> str | None:
    for carrier, pat in CARRIER_PATTERNS.items():
        if pat.search(text):
            return carrier
    return None


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_so_text(text: str) -> dict[str, Any]:
    """主入口 - 从 OCR 文本提取字段"""
    if not text:
        return {}

    result: dict[str, Any] = {}

    # 船公司
    carrier = _detect_carrier(text)
    if carrier:
        result["carrier"] = carrier

    # SO / BL / Booking 编号
    if m := RE_SO_NUMBER.search(text):
        result["so_number"] = m.group(1).strip()
    if m := RE_BL_NUMBER.search(text):
        result["bl_number"] = m.group(1).strip()

    # Vessel + Voyage
    if m := RE_VESSEL.search(text):
        result["vessel_name"] = m.group(1).strip()[:64]
    if m := RE_VOYAGE.search(text):
        result["voyage_no"] = m.group(1).strip()

    # POL / POD
    if m := RE_PORT.search(text):
        result["pol"] = m.group(1).strip()[:64]
    if m := RE_POD.search(text):
        result["pod"] = m.group(1).strip()[:64]

    # 柜型 / 数量
    if m := RE_CONTAINER_TYPE.search(text):
        result["container_type"] = m.group(1).upper()
    if m := RE_CONTAINER_COUNT.search(text):
        result["container_count"] = int(m.group(1))

    # 日期: 第一个出现的当 ETD, 后面若有更多就挑最大的当 ETA (粗糙)
    dates: list[datetime] = []
    for m in RE_DATE.finditer(text):
        d = _parse_date(m.group(1))
        if d:
            dates.append(d)
    for m in RE_DATE2.finditer(text):
        d = _parse_date(m.group(1))
        if d:
            dates.append(d)
    if dates:
        result["etd"] = dates[0]
        if len(dates) > 1:
            result["eta"] = max(dates[1:], key=lambda x: x)

    return result


def load_carrier_templates(path: Path | str) -> dict[str, Any]:
    """加载船公司模板 (JSON) - 用户可自定义"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("已加载船公司模板: {} 条", len(data))
        return data
    except Exception as e:
        logger.warning("加载船公司模板失败: {}", e)
        return {}
