"""v0.5 领域基座 - 公用 mixin / 通用 enum"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """created_at / updated_at

    v0.4 沿用: Python 端 datetime.now(timezone.utc) 带微妙精度, 避免 SQLite 秒级不稳定.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class OrganizationScopedMixin:
    """多租户预留: 所有业务表加 organization_id

    v0.5 单租户, UI 不暴露切换. v0.6 接真多租户时, 在中间件/Depends 里强制 context.
    """

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        doc="FK→organizations.id, multi-tenant 预留",
    )


class AuditAction(str, enum.Enum):
    """AuditLog.action 枚举 (v0.5)"""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    STAGE_CHANGE = "stage_change"
    CANCEL = "cancel"
    ACCEPT = "accept"
    REJECT = "reject"
    SEND = "send"
    MATCH = "match"
    UPLOAD = "upload"
    OCR_DONE = "ocr_done"
    RESOLVE = "resolve"
    AUTO_CLOSE = "auto_close"
    RECORD = "record"  # 通用 record, 兜底


class AuditActorType(str, enum.Enum):
    """AuditLog.actor_type"""

    USER = "user"
    SYSTEM = "system"
    SCHEDULED_JOB = "scheduled_job"
    API = "api"


class PartnerType(str, enum.Enum):
    """合作方类型 (替代 v0.4 Agent)"""

    CUSTOMER = "customer"
    CARRIER = "carrier"
    AGENT_L1 = "agent_l1"  # 一级代理
    AGENT_L2 = "agent_l2"  # 二级代理
    TRUCKING = "trucking"  # 拖车
    WAREHOUSE = "warehouse"  # 仓库
    CUSTOMS_BROKER = "customs_broker"  # 报关行


class JobNoResetPolicy(str, enum.Enum):
    """业务编号重置策略 (Organization 级别)"""

    DAILY = "daily"
    MONTHLY = "monthly"
    NEVER = "never"
