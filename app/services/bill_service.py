"""账单 OCR 服务 - 上传后跑 OCR + 字段提取"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.bill import Bill, BillStatus
from app.services.bill_parser import parse_bill_text
from app.services.ocr_service import ocr_file


async def process_bill_ocr(bill_id: str) -> None:
    """后台任务: 跑 OCR + 字段提取"""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            bill = (await db.execute(select(Bill).where(Bill.id == bill_id))).scalar_one_or_none()
            if not bill:
                logger.error("Bill 不存在: {}", bill_id)
                return
            if not bill.file_path:
                bill.status = BillStatus.OCR_FAILED
                bill.ocr_error = "file_path is empty"
                await db.commit()
                return

            bill.status = BillStatus.OCR_PROCESSING
            await db.commit()

            result = await ocr_file(bill.file_path)
            bill.ocr_text = result.text
            bill.ocr_engine = result.engine
            bill.ocr_confidence = result.confidence
            bill.ocr_at = datetime.now(timezone.utc)

            if result.error:
                bill.status = BillStatus.OCR_FAILED
                bill.ocr_error = result.error
            else:
                fields = parse_bill_text(result.text)
                for k, v in fields.items():
                    if k in ("line_items", "extra_fields"):
                        continue
                    if hasattr(bill, k) and getattr(bill, k) is None and v is not None:
                        setattr(bill, k, v)
                if fields.get("line_items"):
                    bill.line_items = fields["line_items"]
                bill.extra_fields = fields
                bill.status = BillStatus.OCR_DONE if result.text else BillStatus.OCR_FAILED
                if not result.text:
                    bill.ocr_error = "OCR returned empty text"
            await db.commit()
            logger.info(
                "账单 OCR 完成: id={} engine={} conf={}", bill_id, result.engine, result.confidence
            )
        except Exception as e:
            logger.exception("账单 OCR 失败: id={}", bill_id)
            try:
                bill = (
                    await db.execute(select(Bill).where(Bill.id == bill_id))
                ).scalar_one_or_none()
                if bill:
                    bill.status = BillStatus.OCR_FAILED
                    bill.ocr_error = str(e)
                    await db.commit()
            except Exception:
                pass


def save_bill_file(content: bytes, filename: str) -> tuple[Path, int]:
    """保存账单文件到 uploads/bills/"""
    suffix = Path(filename).suffix.lower() or ".bin"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    target_dir = settings.upload_dir / "bills"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{timestamp}{suffix}"
    target.write_bytes(content)
    return target, len(content)
