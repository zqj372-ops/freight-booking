"""v0.6 清单复核 数据模型

v0.6.2: 操作员日常"清单复核"自动化
- ChecklistReview: 一次复核任务 (签收前 / 装船前 / 截关前)
- ChecklistItem: 复核项 (4 大类 14 项: 柜号/封条/柜型/件数/重量/体积/HS/危险品/超大件/4 个文件齐套度)
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._base import OrganizationScopedMixin, TimestampMixin


class ChecklistReviewType(str, enum.Enum):
    """复核时机"""

    PRE_LOAD = "pre_load"           # 装船前 (柜号/封条)
    PRE_CUTOFF = "pre_cutoff"        # 截关前 (文件齐套度)
    PRE_DEPARTURE = "pre_departure"  # 开船前 (综合)
    RANDOM = "random"                # 任意时刻 (运营自查)


class ChecklistReviewStatus(str, enum.Enum):
    """复核状态"""

    DRAFT = "draft"           # 草稿 (跑完规则, 未签收)
    COMPLETED = "completed"   # 已完成 (操作员确认)
    SIGNED_OFF = "signed_off"  # 已签收 (formal ack, 用于发船)
    AUTO_CLOSED = "auto_closed"  # 自动关闭 (操作员未处理, shipment 关单)


class ChecklistItemCategory(str, enum.Enum):
    """复核项分类 (4 大类)"""

    CONTAINER = "container"        # 柜号 + 封条 + 柜型
    DECLARATION = "declaration"    # 件数 + 重量 + 体积 (申报 vs 实际)
    HS_CODE = "hs_code"            # HS code + 危险品/超大件
    CUTOFF_DOC = "cutoff_doc"      # 截关前文件齐套度 (SI/VGM/CI/PL)


class ChecklistItemCode(str, enum.Enum):
    """14 个具体复核项 code"""

    # CONTAINER (3 项)
    CONTAINER_NO_MISSING = "container_no_missing"      # 缺柜号
    CONTAINER_TYPE_MISMATCH = "container_type_mismatch"  # 柜型不符
    CONTAINER_COUNT_MISMATCH = "container_count_mismatch"  # 柜数不符

    # DECLARATION (3 项)
    PIECES_MISMATCH = "pieces_mismatch"        # 件数差
    WEIGHT_MISMATCH = "weight_mismatch"        # 重量差
    VOLUME_MISMATCH = "volume_mismatch"        # 体积差

    # HS_CODE (3 项)
    HS_CODE_MISMATCH = "hs_code_mismatch"              # HS code 差
    DANGEROUS_GOODS_FLAG_MISSING = "dangerous_goods_flag_missing"  # 缺危险品标记
    OVERSIZE_GOODS_FLAG_MISSING = "oversize_goods_flag_missing"    # 缺超大件标记

    # CUTOFF_DOC (4 项, 截关前必传)
    SI_MISSING = "si_missing"        # SI 未传
    VGM_MISSING = "vgm_missing"      # VGM 未传
    CI_MISSING = "ci_missing"        # CI 未传
    PL_MISSING = "pl_missing"        # PL 未传

    # 容器字段辅助
    SEAL_NO_MISSING = "seal_no_missing"  # 缺封条号 (CONTAINER 类别, 14 项之一)


class ChecklistSeverity(str, enum.Enum):
    """复核项严重度"""

    PASS = "pass"          # 符合
    WARNING = "warning"    # 警告 (差异小, 可放过)
    CRITICAL = "critical"  # 严重 (差异大, 必查)


class ChecklistReview(Base, OrganizationScopedMixin, TimestampMixin):
    """一次清单复核任务"""

    __tablename__ = "checklist_reviews"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    review_type: Mapped[ChecklistReviewType] = mapped_column(
        Enum(ChecklistReviewType), nullable=False, index=True,
    )
    status: Mapped[ChecklistReviewStatus] = mapped_column(
        Enum(ChecklistReviewStatus), default=ChecklistReviewStatus.DRAFT, nullable=False, index=True,
    )
    # 跑规则时间 (DRAFT 时 = 自动跑完时间)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # 操作员签收时间
    signed_off_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by_user_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 汇总
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critical_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overall_severity: Mapped[ChecklistSeverity] = mapped_column(
        Enum(ChecklistSeverity), default=ChecklistSeverity.PASS, nullable=False,
    )
    # 触发本次复核的原因 (e.g. "装船前自动触发" / "操作员手动启动")
    trigger_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 自动建的异常 ID 列表 (本复核触发的 OperationalException)
    related_exception_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # 备注
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 复核时的 shipment 快照 (用于历史回看)
    shipment_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_checklist_reviews_org_shipment", "organization_id", "shipment_id"),
    )

    def __repr__(self) -> str:
        return f"<ChecklistReview {self.id} ship={self.shipment_id[:8]} type={self.review_type.value} status={self.status.value}>"


class ChecklistItem(Base, OrganizationScopedMixin, TimestampMixin):
    """清单复核项 (14 个 code, 1 review 1 item)"""

    __tablename__ = "checklist_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    review_id: Mapped[str] = mapped_column(
        ForeignKey("checklist_reviews.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    code: Mapped[ChecklistItemCode] = mapped_column(
        Enum(ChecklistItemCode), nullable=False, index=True,
    )
    category: Mapped[ChecklistItemCategory] = mapped_column(
        Enum(ChecklistItemCategory), nullable=False, index=True,
    )
    label: Mapped[str] = mapped_column(
        String(128), nullable=False,
        doc="中文标签 (e.g. '柜号一致性')",
    )
    expected_value: Mapped[str | None] = mapped_column(
        String(256), nullable=True,
        doc="期望值 (e.g. '40HQ x 2' / '150 件')",
    )
    actual_value: Mapped[str | None] = mapped_column(
        String(256), nullable=True,
        doc="实际值 (e.g. '40HQ x 1')",
    )
    match: Mapped[bool] = mapped_column(
        default=True, nullable=False,
        doc="True=PASS, False=FAIL (warning/critical)",
    )
    severity: Mapped[ChecklistSeverity] = mapped_column(
        Enum(ChecklistSeverity), nullable=False,
    )
    # 差异 (numeric 字段, e.g. 件数差 5 件, 重量差 100kg)
    delta: Mapped[float | None] = mapped_column(
        nullable=True, doc="差值 (numeric 字段, e.g. 件数差 / 重量差 kg)",
    )
    delta_pct: Mapped[float | None] = mapped_column(
        nullable=True, doc="差值百分比 (0-100)",
    )
    # 数据来源 (哪个 document 提取的, 哪个 container 触发的)
    related_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    related_container_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 用户备注 (操作员标记已确认)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 用户是否已确认 (warning 项操作员可强制 pass)
    acknowledged_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("ix_checklist_items_review", "review_id"),
        Index("ix_checklist_items_org_severity", "organization_id", "severity"),
    )

    def __repr__(self) -> str:
        return f"<ChecklistItem {self.code.value} match={self.match} severity={self.severity.value}>"


__all__ = [
    "ChecklistReview",
    "ChecklistItem",
    "ChecklistReviewType",
    "ChecklistReviewStatus",
    "ChecklistItemCategory",
    "ChecklistItemCode",
    "ChecklistSeverity",
]
