"""fix v0.4 schema

Revision ID: 999c813c4675
Revises: 53bbe0e83786
Create Date: 2026-08-20 09:46:08.963539

v0.5 阶段 0 修: 这个 migration 原本是 alembic autogenerate 误生成的, 重复创建
9 张已存在的表. v0.4 之前用 init_db() 部署, 真实 schema 跟 SQLAlchemy model 完全
一致, 此 migration 实际是 no-op.

修复: 改成空 upgrade/downgrade, 仅为 alembic 链完整性存在. 真正的 v0.4 字段
(matched_booking_id / payment_method / payment_ref) 由 53bbe0e83786 添加.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '999c813c4675'
down_revision: Union[str, None] = '53bbe0e83786'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # no-op: v0.4 真实 schema 已由前序 migration 创建, 此处无新增.
    # 保留 revision 仅用于 alembic 链完整性.
    pass


def downgrade() -> None:
    # no-op
    pass
