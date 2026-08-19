"""业务辅助 - 自动生成 booking_no / 状态机"""

import random
import string
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking, BookingStatus


def generate_booking_no(carrier: str | None = None) -> str:
    """生成订舱号 - YYYYMMDD + 4位随机"""
    today = datetime.now().strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    prefix = (carrier or "FB")[:3].upper()
    return f"{prefix}-{today}-{suffix}"


async def next_booking_no(db: AsyncSession, carrier: str | None = None) -> str:
    """确保唯一 - 重复就重试"""
    for _ in range(5):
        no = generate_booking_no(carrier)
        exists = (
            await db.execute(select(Booking.id).where(Booking.booking_no == no))
        ).scalar_one_or_none()
        if not exists:
            return no
    raise RuntimeError("生成唯一 booking_no 失败")


VALID_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.DRAFT: {BookingStatus.SUBMITTED, BookingStatus.CANCELLED},
    BookingStatus.SUBMITTED: {
        BookingStatus.CONFIRMED,
        BookingStatus.REJECTED,
        BookingStatus.CANCELLED,
    },
    BookingStatus.CONFIRMED: {BookingStatus.COMPLETED, BookingStatus.CANCELLED},
    BookingStatus.REJECTED: {BookingStatus.DRAFT},
    BookingStatus.CANCELLED: {BookingStatus.DRAFT},
    BookingStatus.COMPLETED: set(),
}


def can_transition(from_: BookingStatus, to: BookingStatus) -> bool:
    return to in VALID_TRANSITIONS.get(from_, set())
