"""AuditLog (操作审计) 模型 - v0.5"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._base import AuditAction, AuditActorType, OrganizationScopedMixin, TimestampMixin


class AuditLog(Base, OrganizationScopedMixin, TimestampMixin):
    """任何写操作自动留痕 (Shipment / BookingRequest / BookingConfirmation / Document / Task / Exception / Milestone / EmailMessage).

    actor 取值策略 (v0.5 拍板):
    - JWT 暂不实现, 从 request header `X-User-Id` (UUID) + `X-User-Name` 取
    - 没传则: actor_type=API, actor_user_id=NULL, actor_job_name='api_call'
    - 调度任务: actor_type=SCHEDULED_JOB, actor_job_name='imap_poll' 等
    - 系统内部触发: actor_type=SYSTEM, actor_user_id=NULL
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # 变更对象
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        doc="实体类型: shipment / booking_request / booking_confirmation / document / task / operational_exception / milestone / email_message / partner ...",
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
        doc="实体 ID (UUID)",
    )

    # 动作
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction), nullable=False, index=True,
    )

    # 变更详情
    field_changes: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, doc='{"field": {"old": ..., "new": ...}}',
    )
    context: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, doc="request_id / ip / user_agent / reason",
    )

    # 操作者
    actor_type: Mapped[AuditActorType] = mapped_column(
        Enum(AuditActorType), nullable=False, default=AuditActorType.API,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True, doc="FK→users.id, 暂未实现",
    )
    actor_user_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, doc="冗余存 user name, 方便审计展示",
    )
    actor_job_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="例: 'imap_poll' / 'api_call' / 'migrate_v04_to_v05'",
    )

    # sensitive 操作的 reason
    reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="sensitive 操作 (accept/reject/cancel/delete) 必填, min 5 字符",
    )

    __table_args__ = (
        Index("ix_audit_org_entity", "organization_id", "entity_type", "entity_id"),
        Index("ix_audit_org_action_time", "organization_id", "action", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.entity_type}:{self.entity_id} {self.action.value} by {self.actor_type.value}>"
