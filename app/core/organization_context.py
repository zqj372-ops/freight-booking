"""v0.5 organization context 工具

v0.5 单租户运行, 每次请求从 DB 拿默认 Organization. 后续 v0.6 接真多租户时,
此处可改为从 request header / JWT 取 organization_id.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization

DEFAULT_ORG_SLUG = "default-company"


async def get_default_organization(db: AsyncSession) -> Organization:
    """拿默认 organization (seed slug='default-company')

    如果 DB 里没有, 主动 seed 一条 (开发友好).
    """
    stmt = select(Organization).where(Organization.slug == DEFAULT_ORG_SLUG)
    org = (await db.execute(stmt)).scalar_one_or_none()
    if org:
        return org
    org = Organization(
        slug=DEFAULT_ORG_SLUG,
        display_name="二掌柜货代",
        job_no_prefix="FB",
        job_no_date_fmt="YYYYMMDD",
        job_no_seq_digits=4,
        job_no_reset_policy="daily",
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def ensure_default_organization_exists(db: AsyncSession) -> Organization:
    """启动时 seed (幂等)"""
    return await get_default_organization(db)
