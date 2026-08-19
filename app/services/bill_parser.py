"""账单 OCR 解析 - PaddleOCR 文本 → 结构化字段

支持的字段（增值税发票通用格式 + 海运费发票）:
- 发票代码 / 发票号码 (bill_no)
- 开票日期 / 到期日
- 销售方 / 购买方 (名称 + 税号)
- 价税合计 / 不含税金额 / 税额
- 币种
- 明细行 (货物/数量/单价/金额/税率/税额)
- 备注

预留 LLM 增强入口 (LLMExtractor), 默认走规则
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


# 增值税发票标准字段正则
RE_INVOICE_CODE = re.compile(r"发票代码\s*[:：]?\s*(\d{10,12})")
RE_INVOICE_NO = re.compile(r"发票号码\s*[:：]?\s*(\d{8,20})")
RE_BILL_NO_GENERIC = re.compile(r"(?:Invoice\s*No|Bill\s*No|账单号|票据号)\s*[:：]?\s*([A-Z0-9\-]{6,})", re.I)

RE_DATE = re.compile(r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})")
RE_DATE2 = re.compile(r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})")

RE_SELLER = re.compile(r"(?:销售方|开票方|Seller|From)\s*[:：]?\s*名称?\s*[:：]?\s*([^\n]+?公司|[^\n]+?厂|[^\n]+?店|[^\n]{4,80})", re.I)
RE_SELLER_TAX = re.compile(r"销售方[^\n]*?纳税人识别号\s*[:：]?\s*([A-Z0-9]{15,20})")
RE_BUYER = re.compile(r"(?:购买方|购货方|收货方|Buyer|To|Bill\s*To)\s*[:：]?\s*名称?\s*[:：]?\s*([^\n]+?公司|[^\n]+?厂|[^\n]+?店|[^\n]{4,80})", re.I)
RE_BUYER_TAX = re.compile(r"购买方[^\n]*?纳税人识别号\s*[:：]?\s*([A-Z0-9]{15,20})")

# 价税合计 (小写) - 最常见
RE_TOTAL = re.compile(r"价税合计[^\d]*?[¥￥$€]?\s*([\d,]+\.?\d*)", re.I)
RE_TAX = re.compile(r"(?:税额|增值税额)\s*[:：]?\s*[¥￥$€]?\s*([\d,]+\.?\d*)", re.I)
RE_EXCL_TAX = re.compile(r"(?:不含税|金额合计|合计金额)\s*[:：]?\s*[¥￥$€]?\s*([\d,]+\.?\d*)", re.I)

# 大写金额
RE_AMOUNT_CN = re.compile(r"价税合计.*?（大写）.*?\n?\s*([壹贰叁肆伍陆柒捌玖拾佰仟万亿圆角分零整]+)")

# 币种
CURRENCY_HINTS = {
    "CNY": ["人民币", "¥", "￥", "RMB", "CNY"],
    "USD": ["美元", "US$", "USD", "$"],
    "EUR": ["欧元", "€", "EUR"],
    "HKD": ["港币", "HK$", "HKD"],
    "JPY": ["日元", "JPY", "¥"],
}


def _detect_currency(text: str) -> str:
    for cur, hints in CURRENCY_HINTS.items():
        for h in hints:
            if h in text:
                # 排除 USD 误判 (HKD 也含 $)
                if h == "$" and "US$" not in text and "USD" not in text and "HK$" not in text:
                    continue
                return cur
    return "CNY"


def _parse_amount(s: str) -> float | None:
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(s: str) -> datetime | None:
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _detect_bill_kind(text: str) -> str:
    """判断发票类型"""
    if "增值税专用发票" in text:
        return "vat_special"
    if "增值税电子" in text or "电子发票" in text:
        return "vat_electronic"
    if "增值税普通发票" in text:
        return "vat_normal"
    if "海运费" in text or "OCEAN FREIGHT" in text.upper():
        return "ocean_freight"
    if "滞箱" in text or "DETENTION" in text.upper():
        return "detention"
    return "other"


def _parse_line_items(text: str) -> list[dict[str, Any]]:
    """解析明细行 - 启发式: 找带税率的行 + 数字"""
    items: list[dict[str, Any]] = []
    # 常见格式: 货物名称 数量 单价 金额 税率 税额
    # 行匹配: 字符+数字+数字+数字+13%/3%等+数字
    pattern = re.compile(
        r"(?P<name>[^\n]{2,40}?)\s+"
        r"(?P<qty>[\d.,]+)\s+"
        r"(?P<unit_price>[\d.,]+)\s+"
        r"(?P<amount>[\d.,]+)\s+"
        r"(?P<tax_rate>\d+(?:\.\d+)?)\s*%\s+"
        r"(?P<tax_amount>[\d.,]+)"
    )
    for m in pattern.finditer(text):
        try:
            items.append(
                {
                    "name": m.group("name").strip(),
                    "quantity": float(m.group("qty").replace(",", "")),
                    "unit_price": float(m.group("unit_price").replace(",", "")),
                    "amount": float(m.group("amount").replace(",", "")),
                    "tax_rate": float(m.group("tax_rate")),
                    "tax_amount": float(m.group("tax_amount").replace(",", "")),
                }
            )
        except ValueError:
            continue
    return items


def parse_bill_text(text: str) -> dict[str, Any]:
    """主入口 - 从 OCR 文本提取账单字段"""
    if not text:
        return {}

    result: dict[str, Any] = {
        "bill_kind": _detect_bill_kind(text),
        "currency": _detect_currency(text),
    }

    # 发票号
    if m := RE_INVOICE_CODE.search(text):
        result["invoice_code"] = m.group(1)
    if m := RE_INVOICE_NO.search(text):
        result["bill_no"] = m.group(1)
    elif m := RE_BILL_NO_GENERIC.search(text):
        result["bill_no"] = m.group(1)

    # 购销方
    if m := RE_SELLER.search(text):
        result["seller_name"] = m.group(1).strip()[:128]
    if m := RE_SELLER_TAX.search(text):
        result["seller_tax_no"] = m.group(1)
    if m := RE_BUYER.search(text):
        result["buyer_name"] = m.group(1).strip()[:128]
    if m := RE_BUYER_TAX.search(text):
        result["buyer_tax_no"] = m.group(1)

    # 金额
    if m := RE_TOTAL.search(text):
        result["total_amount"] = _parse_amount(m.group(1))
    if m := RE_TAX.search(text):
        result["tax_amount"] = _parse_amount(m.group(1))
    if m := RE_EXCL_TAX.search(text):
        result["amount_excl_tax"] = _parse_amount(m.group(1))

    # 校验: 价税合计 = 不含税 + 税额 (允许 0.01 误差)
    if result.get("total_amount") and result.get("amount_excl_tax") and not result.get("tax_amount"):
        diff = result["total_amount"] - result["amount_excl_tax"]
        if 0 <= diff < result["total_amount"] * 0.2:
            result["tax_amount"] = round(diff, 2)
    if result.get("total_amount") and result.get("tax_amount") and not result.get("amount_excl_tax"):
        result["amount_excl_tax"] = round(result["total_amount"] - result["tax_amount"], 2)

    # 日期
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
        result["issued_at"] = dates[0]

    # 明细
    items = _parse_line_items(text)
    if items:
        result["line_items"] = items

    return result


# ====== LLM 增强预留 (可选) ======


class LLMExtractor:
    """用 LLM (Gemini/GPT) 做结构化提取 - 高准确率但需 API key

    用法:
        extractor = LLMExtractor(api_key="...", model="gemini-1.5-flash")
        fields = await extractor.extract(text)
    """

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash", base_url: str | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    async def extract(self, text: str) -> dict[str, Any]:
        """异步调 LLM, 返回结构化字段"""
        # TODO: 接入 LLM API
        # 这里只做占位, 实际接入时用 httpx 调 Gemini/OpenAI
        raise NotImplementedError("LLM extractor 待实现 - 后续可接入 Gemini/OpenAI")
