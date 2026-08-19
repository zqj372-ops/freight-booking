"""Pydantic schemas"""

from app.schemas.so import (  # noqa: F401
    SOBase,
    SOCreate,
    SORead,
    SOUpdate,
    SOListItem,
    SOListResponse,
)
from app.schemas.booking import (  # noqa: F401
    BookingBase,
    BookingCreate,
    BookingRead,
    BookingUpdate,
    BookingListResponse,
)
from app.schemas.agent import (  # noqa: F401
    AgentBase,
    AgentCreate,
    AgentRead,
    AgentUpdate,
)
from app.schemas.email import (  # noqa: F401
    EmailTemplateCreate,
    EmailTemplateRead,
    EmailTemplateUpdate,
    EmailLogRead,
    EmailSendRequest,
)
