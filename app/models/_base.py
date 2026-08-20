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


class BusinessPhase(int, enum.Enum):
    """v0.5 1.5 业务阶段 8 段 (UI 进度条用, 1-8 编号)

    推导逻辑 (see app/services/workflow.py derive_business_phase):
    - Milestone 里最早到达的最高级 phase
    - 没 milestone → 1
    - departed/arrived → 7
    - empty_returned → 8 (completed)
    """

    BUILD = 1  # 1 建业务 (draft)
    BOOKING = 2  # 2 发订舱
    SO_REVIEW = 3  # 3 收/核 SO
    PICKUP_LOAD = 4  # 4 提柜装柜
    SI_BL = 5  # 5 补料提单
    CUSTOMS = 6  # 6 报关放行
    DEPARTED = 7  # 7 开船到港
    COMPLETED = 8  # 8 结案还柜


class PhaseColor(str, enum.Enum):
    """8 业务阶段进度条颜色 (UI 渲染)"""

    COMPLETED = "completed"  # 绿
    IN_PROGRESS = "in_progress"  # 蓝
    WAITING_EXTERNAL = "waiting_external"  # 紫
    APPROACHING_DEADLINE = "approaching_deadline"  # 黄 (within 4h)
    OVERDUE = "overdue"  # 红
    NOT_STARTED = "not_started"  # 灰


class CustomsStatus(str, enum.Enum):
    """v0.5 1.5 报关状态 (替代 Y/N)"""

    PENDING = "pending"  # 待申报
    SUBMITTING = "submitting"  # 申报中
    RELEASED = "released"  # 已放行
    REJECTED = "rejected"  # 退单
    INSPECTING = "inspecting"  # 查验


class InspectionStatus(str, enum.Enum):
    """v0.5 1.5 查验状态 (替代 Y/N)"""

    NOT_RECEIVED = "not_received"
    RECEIVED = "received"
    HANDLING = "handling"
    COMPLETED = "completed"


class RolledStatus(str, enum.Enum):
    """v0.5 1.5 甩柜状态 (替代 Y/N)"""

    NOT_HAPPENED = "not_happened"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"
    REALLOCATED = "reallocated"
    CLOSED = "closed"


class PaymentRequestStatus(str, enum.Enum):
    """v0.5 1.5 请款/预付款状态"""

    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    APPROVED = "approved"
    PAID = "paid"


class PaymentProofStatus(str, enum.Enum):
    """v0.5 1.5 水单状态"""

    NOT_PROVIDED = "not_provided"
    PROVIDED = "provided"
    CONFIRMED = "confirmed"


class EmptyReturnStatus(str, enum.Enum):
    """v0.5 1.5 还空柜状态"""

    NOT_SCHEDULED = "not_scheduled"
    SCHEDULED = "scheduled"
    RETURNED = "returned"
    OVERDUE = "overdue"
    ABNORMAL = "abnormal"


class BlProcessStatus(str, enum.Enum):
    """v0.5 1.5 提单处理状态 (替代 Y/N)"""

    NOT_STARTED = "not_started"
    DRAFT_RECEIVED = "draft_received"
    REVISING = "revising"
    CONFIRMED = "confirmed"
    ABNORMAL = "abnormal"


class ExceptionLevel(str, enum.Enum):
    """v0.5 1.5 异常等级 (替代 Y/N)"""

    NORMAL = "normal"
    GENERAL = "general"
    IMPORTANT = "important"
    URGENT = "urgent"


# 业务阶段中文名 (UI 渲染用, v0.5 1.5)
PHASE_LABELS: dict[int, str] = {
    1: "建业务",
    2: "发订舱",
    3: "收/核 SO",
    4: "提柜装柜",
    5: "补料提单",
    6: "报关放行",
    7: "开船到港",
    8: "结案还柜",
}
