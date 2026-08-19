"""ORM models - 全部 import 让 Base 知道"""

from app.models.so import SO, SOStatus  # noqa: F401
from app.models.booking import Booking, BookingStatus  # noqa: F401
from app.models.agent import Agent  # noqa: F401
from app.models.email_template import EmailTemplate  # noqa: F401
from app.models.email_log import EmailLog, EmailStatus  # noqa: F401
from app.models.bill import Bill, BillStatus, BillKind  # noqa: F401
from app.models.tracking import TrackingEvent, TrackingStatus, TrackingSource  # noqa: F401

__all__ = [
    "SO",
    "SOStatus",
    "Booking",
    "BookingStatus",
    "Agent",
    "EmailTemplate",
    "EmailLog",
    "EmailStatus",
    "Bill",
    "BillStatus",
    "BillKind",
    "TrackingEvent",
    "TrackingStatus",
    "TrackingSource",
]
