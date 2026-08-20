"""Partner (合作方) 模型 - v0.5 替代 v0.4 Agent"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._base import OrganizationScopedMixin, PartnerType, TimestampMixin


class Partner(Base, OrganizationScopedMixin, TimestampMixin):
    """合作方: 客户/船公司/一级代理/二级代理/拖车/仓库/报关行.

    替代 v0.4 Agent. 字段做了扩展:
    - `partner_type` 区分合作方种类
    - `preferred_routes` / `preferred_carriers` 业务专长
    - `response_sla_hours` SLA 配置
    - 软删: `is_active` 标记, 不物理删除
    """

    __tablename__ = "partners"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # 类型与名称
    partner_type: Mapped[PartnerType] = mapped_column(
        Enum(PartnerType), nullable=False, index=True,
        doc="customer / carrier / agent_l1 / agent_l2 / trucking / warehouse / customs_broker",
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, doc="合作方名称",
    )
    short_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="简短代码, 用于邮件主题快速引用",
    )

    # 联系方式
    primary_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True, doc="主联系邮箱",
    )
    cc_emails: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False, doc="抄送邮箱列表",
    )
    contact_person: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_wechat: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 业务专长
    preferred_routes: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False, doc="擅长航线, e.g. ['CNSHA-USLAX', 'CNSHA-CAVAN']",
    )
    preferred_carriers: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False, doc="可订船公司, e.g. ['MAERSK', 'MSC']",
    )
    response_sla_hours: Mapped[int | None] = mapped_column(
        nullable=True, doc="响应 SLA 小时数, BookingRequest 超时判定用",
    )

    # 默认模板 (FK→email_templates.id, v0.5 暂不绑, 留字段)
    default_template_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, doc="发该合作方的默认邮件模板",
    )

    # 档案
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    __table_args__ = (
        # 同组织下 short_code 唯一 (空值允许多个)
        UniqueConstraint("organization_id", "short_code", name="uq_partners_org_short_code"),
        Index("ix_partners_org_type", "organization_id", "partner_type"),
        Index("ix_partners_org_name", "organization_id", "name"),
    )

    def __repr__(self) -> str:
        return f"<Partner {self.partner_type.value} {self.name}>"
