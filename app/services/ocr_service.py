"""OCR 服务 - PaddleOCR 封装, 支持 PDF/图片

PaddleOCR 较重, 没装时降级到 mock 模式(返回空文本, 业务仍可跑)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings


@dataclass
class OCRResult:
    text: str
    confidence: float  # 0~1
    engine: str
    raw: list[list[Any]] = field(default_factory=list)
    error: str | None = None


def _is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def _pdf_to_images(path: Path) -> list[bytes]:
    """PDF 转图片 (PNG bytes list)"""
    from pdf2image import convert_from_path

    images = convert_from_path(path, dpi=200)
    return [img.tobytes() if hasattr(img, "tobytes") else _pil_to_png_bytes(img) for img in images]


def _pil_to_png_bytes(img) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _image_to_pil(path: Path):
    from PIL import Image

    return Image.open(path)


class PaddleOCREngine:
    """PaddleOCR 引擎 - 懒加载, 失败降级到 mock"""

    def __init__(self) -> None:
        self._ocr = None
        self._available: bool | None = None
        self._err: str | None = None

    def _ensure_loaded(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            from paddleocr import PaddleOCR  # type: ignore

            kwargs: dict[str, Any] = {
                "use_angle_cls": settings.paddleocr_use_angle_cls,
                "lang": settings.paddleocr_lang,
                "show_log": False,
            }
            if settings.paddleocr_use_gpu:
                kwargs["use_gpu"] = True
            if settings.paddleocr_model_dir:
                kwargs["det_model_dir"] = f"{settings.paddleocr_model_dir}/det"
                kwargs["rec_model_dir"] = f"{settings.paddleocr_model_dir}/rec"
                kwargs["cls_model_dir"] = f"{settings.paddleocr_model_dir}/cls"

            self._ocr = PaddleOCR(**kwargs)
            self._available = True
            logger.info("PaddleOCR 加载成功 lang={}", settings.paddleocr_lang)
        except Exception as e:
            self._available = False
            self._err = str(e)
            logger.warning("PaddleOCR 不可用, 降级到 mock: {}", e)
        return self._available

    def ocr(self, path: Path) -> OCRResult:
        if not self._ensure_loaded():
            return OCRResult(
                text="",
                confidence=0.0,
                engine="mock",
                error=self._err or "paddleocr not installed",
            )

        try:
            if _is_pdf(path):
                # PDF: 转图后逐页识别
                from pdf2image import convert_from_path  # noqa: F401

                images = convert_from_path(path, dpi=200)
                texts: list[str] = []
                confs: list[float] = []
                raws: list[Any] = []
                import numpy as np  # noqa: F401

                for img in images:
                    arr = np.array(img)
                    res = self._ocr.ocr(arr, cls=True)  # type: ignore
                    page_text, page_conf, page_raw = _flatten_paddle_result(res)
                    texts.append(page_text)
                    confs.append(page_conf)
                    raws.extend(page_raw or [])
                text = "\n\n".join(t for t in texts if t)
                confidence = sum(confs) / len(confs) if confs else 0.0
                return OCRResult(text=text, confidence=confidence, engine="paddleocr", raw=raws)
            else:
                # 图片
                res = self._ocr.ocr(str(path), cls=True)  # type: ignore
                text, conf, raw = _flatten_paddle_result(res)
                return OCRResult(text=text, confidence=conf, engine="paddleocr", raw=raw or [])
        except Exception as e:
            logger.exception("OCR 失败: {}", e)
            return OCRResult(text="", confidence=0.0, engine="paddleocr", error=str(e))


def _flatten_paddle_result(res) -> tuple[str, float, list[Any] | None]:
    """PaddleOCR 返回 [[box, (text, conf)], ...] 拍平"""
    if not res or not res[0]:
        return "", 0.0, None
    lines: list[str] = []
    confs: list[float] = []
    for line in res[0]:
        # line: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], (text, conf)
        if not line or len(line) < 2:
            continue
        text_conf = line[1]
        if not text_conf or len(text_conf) < 2:
            continue
        text, conf = text_conf[0], float(text_conf[1])
        if text:
            lines.append(text)
            confs.append(conf)
    avg = sum(confs) / len(confs) if confs else 0.0
    text = "\n".join(lines)
    return text, avg, res[0]


# 单例
_engine: PaddleOCREngine | None = None


def get_ocr_engine() -> PaddleOCREngine:
    global _engine
    if _engine is None:
        _engine = PaddleOCREngine()
    return _engine


async def ocr_file(path: str | Path) -> OCRResult:
    """异步入口 - 实际 OCR 跑在线程池里 (PaddleOCR 同步)"""
    import asyncio

    p = Path(path)
    if not p.exists():
        return OCRResult(text="", confidence=0.0, engine="mock", error=f"file not found: {p}")

    engine = get_ocr_engine()

    def _do() -> OCRResult:
        return engine.ocr(p)

    return await asyncio.to_thread(_do)
