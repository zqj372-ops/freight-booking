"""ORM models - 全部 import 让 Base 知道"""

# v0.4 legacy (阶段 2 切只读)
from app.models.so import SO, SOStatus  # noqa: F401
from app.models.booking import Booking, BookingStatus  # noqa: F401
from app.models.agent import Agent  # noqa: F401
from app.models.email_template import EmailTemplate  # noqa: F401
from app.models.email_log import EmailLog, EmailStatus  # noqa: F401
from app.models.bill import Bill, BillStatus, BillKind  # noqa: F401
from app.models.tracking import TrackingEvent, TrackingStatus, TrackingSource  # noqa: F401
from app.models.email_ingestion import (  # noqa: F401
    EmailIngestion,
    IngestionSource,
    IngestionStatus,
    ProcessedEmail,
)

# v0.5 新增 (阶段 1 逐步上线)
from app.models.organization import Organization  # noqa: F401
from app.models.partner import Partner  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.shipment import Shipment, ShipmentStage  # noqa: F401
from app.models.booking_request import BookingRequest, BookingRequestStatus  # noqa: F401
from app.models.booking_confirmation import (  # noqa: F401
    BookingConfirmation, BookingConfirmationStatus, BookingConfirmationReviewStatus,
)
from app.models.container import Container, ContainerStatus  # noqa: F401
from app.models.document import (  # noqa: F401
    Document, DocumentExtraction,
    DocumentSource, DocumentType, OcrStatus, ParseStatus, ExtractionMethod,
)
from app.models.email import (  # noqa: F401
    EmailThread, EmailMessage,
    EmailThreadStatus, EmailDirection, EmailMessageStatus, EmailSource,
)
from app.models.milestone import Milestone, MilestoneCode, MilestoneSource  # noqa: F401
from app.models.task import Task, TaskCode, TaskStatus  # noqa: F401
from app.models.operational_exception import (  # noqa: F401
    OperationalException, ExceptionCode, ExceptionSeverity, ExceptionStatus, ExceptionDetectedBy,
)

__all__ = [
    # v0.4
    "SO", "SOStatus",
    "Booking", "BookingStatus",
    "Agent",
    "EmailTemplate",
    "EmailLog", "EmailStatus",
    "Bill", "BillStatus", "BillKind",
    "TrackingEvent", "TrackingStatus", "TrackingSource",
    "EmailIngestion", "IngestionSource", "IngestionStatus", "ProcessedEmail",
    # v0.5
    "Organization", "Partner", "AuditLog",
    "Shipment", "ShipmentStage",
    "BookingRequest", "BookingRequestStatus",
    "BookingConfirmation", "BookingConfirmationStatus", "BookingConfirmationReviewStatus",
    "Container", "ContainerStatus",
    "Document", "DocumentExtraction",
    "DocumentSource", "DocumentType", "OcrStatus", "ParseStatus", "ExtractionMethod",
    "EmailThread", "EmailMessage",
    "EmailThreadStatus", "EmailDirection", "EmailMessageStatus", "EmailSource",
    "Milestone", "MilestoneCode", "MilestoneSource",
    "Task", "TaskCode", "TaskStatus",
    "OperationalException", "ExceptionCode", "ExceptionSeverity", "ExceptionStatus", "ExceptionDetectedBy",
]
