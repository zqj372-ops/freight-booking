"""Organization (组织/租户) 模型 - v0.5 core workflow"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._base import JobNoResetPolicy, TimestampMixin


class Organization(Base, TimestampMixin):
    """货代公司 / 租户.

    v0.5 只 seed 一行 `slug='default-company'`. UI 不暴露切换, 但 schema 完全支持多组织.

    每个组织独立持有: shipments / partners / users / email_accounts / email_templates /
    documents / email_threads / tasks / operational_exceptions / audit_logs 等.
    """

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    slug: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False,
        doc="URL-safe 唯一标识, 如 'default-company'",
    )
    display_name: Mapped[str] = mapped_column(
        String(255), nullable=False, doc="组织展示名, 如 '二掌柜货代'",
    )

    # 业务编号规则 (v0.5 全部用默认, v0.6 做规则编辑器)
    job_no_prefix: Mapped[str] = mapped_column(
        String(8), default="FB", nullable=False, doc="job_no 前缀",
    )
    job_no_date_fmt: Mapped[str] = mapped_column(
        String(16), default="YYYYMMDD", nullable=False, doc="job_no 日期段格式",
    )
    job_no_seq_digits: Mapped[int] = mapped_column(
        default=4, nullable=False, doc="job_no 流水位数",
    )
    job_no_reset_policy: Mapped[JobNoResetPolicy] = mapped_column(
        Enum(JobNoResetPolicy),
        default=JobNoResetPolicy.DAILY,
        nullable=False,
        doc="流水重置策略",
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug} {self.display_name}>"
