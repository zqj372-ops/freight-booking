"""Task (待办) 模型 - v0.5

操作员/系统主动创建, 有明确 owner 和 due_time.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin
from app.models.milestone import MilestoneCode

if TYPE_CHECKING:
    from app.models.shipment import Shipment


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskCode(str, enum.Enum):
    """Task 类型 (v0.5 范围)"""

    CONFIRM_SO = "confirm_so"  # 接受 SO 之前必须先确认匹配
    CONFIRM_BOOKING = "confirm_booking"  # 确认 Booking Confirmation 字段
    CONTACT_SUPPLIER = "contact_supplier"  # 联系供应商
    ARRANGE_PICKUP = "arrange_pickup"  # 安排提柜
    RECORD_CONTAINER_NO = "record_container_no"  # 录入柜号
    RECORD_SEAL_NO = "record_seal_no"  # 录入封条号
    SUBMIT_SI = "submit_si"  # 提交 SI
    SUBMIT_VGM = "submit_vgm"  # 提交 VGM
    CONFIRM_CARGO_READY = "confirm_cargo_ready"  # 确认货物就绪
    CONFIRM_LOADED = "confirm_loaded"  # 确认装船
    HANDLE_EXCEPTION = "handle_exception"  # 处理异常
    # v0.5 1.5.3: 16 个新 SLA task code
    SEND_SO_TO_TRUCKER = "send_so_to_trucker"  # 将 SO 发给拖车行 (2h)
    SEND_SI = "send_si"  # 发送 SI 补料 (2h, 资料齐全)
    REVIEW_BL_DRAFT = "review_bl_draft"  # 核对提单草稿/修改件 (30min)
    SEND_CUSTOMS_DOCS = "send_customs_docs"  # 发送出口报关资料 (封柜后 2h)
    CONFIRM_CUSTOMS_RELEASED = "confirm_customs_released"  # 确认出口放行 (CY Cut-off 前)
    HANDLE_INSPECTION = "handle_inspection"  # 处理官方查验 (高优)
    CHECK_DEPARTURE = "check_departure"  # 查询是否开船 (ETD+1d)
    GET_ONBOARD_BL = "get_onboard_bl"  # 取得开船提单 (ATD+2d)
    GET_EMF = "get_emf"  # 取得 EMF (ATD+2d)
    CHECK_ARRIVAL = "check_arrival"  # 查询到港情况 (ETA-3d)
    PAYMENT_REQUEST = "payment_request"  # 发起请款/预付款 (ETA-7d)
    TELEX_BL = "telex_bl"  # 取得电放提单 (ETA-3 工作日)
    GET_ARRIVAL_NOTICE = "get_arrival_notice"  # 取得 AN (ETA 前)
    GET_LOAD_PLAN = "get_load_plan"  # 准备 Load Plan (拆柜前)
    PROVIDE_PROOF = "provide_proof"  # 提供水单 (付款后立即)
    RETURN_EMPTY = "return_empty"  # 归还空柜 (还柜截止前)


class Task(Base, OrganizationScopedMixin, TimestampMixin):
    """待办任务"""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shipment: Mapped["Shipment"] = relationship("Shipment", lazy="joined")

    code: Mapped[TaskCode] = mapped_column(
        Enum(TaskCode), nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )

    assignee_user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    assignee_user_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False, index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    completed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    auto_close_on: Mapped[MilestoneCode | None] = mapped_column(
        Enum(MilestoneCode), nullable=True,
        doc="录入对应 Milestone 时自动 mark done",
    )
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_tasks_org_shipment", "organization_id", "shipment_id"),
        Index("ix_tasks_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Task {self.code.value} {self.title} {self.status.value}>"
