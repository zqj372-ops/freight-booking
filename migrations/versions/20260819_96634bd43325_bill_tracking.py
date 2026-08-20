"""bill+tracking

Revision ID: 96634bd43325
Revises: 231db57b5b6f
Create Date: 2026-08-19 22:03:30.155329

v0.5 阶段 0 修: 这个 migration 原本是 alembic autogenerate 误生成的, 重复创建了
init_schema (231db57b5b6f) 已有的 agents / email_logs / email_templates / bookings /
bills / sos 表. v0.4 之前用 init_db() (SQLAlchemy create_all) 部署, 这个 bug 没暴露.
v0.5 阶段 2 切到 alembic upgrade head 时, 重复 create 会报 "table already exists".

修复: 删掉重复 create_table, 只保留 tracking_events (本 migration 真正新增的表).
v0.5 阶段 1.1 之前手动应用此修复 (commit 9e32a03 之后, 当前 commit 的 fix 包含).

如果之前已用旧版 96634bd43325 跑过, 这张表已经存在, alembic 会认为这个 migration 已应用.
如果从干净 DB 跑, 走新版 migration 逻辑.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96634bd43325'
down_revision: Union[str, None] = '231db57b5b6f'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 只创建 tracking_events (本 migration 真正新增).
    # 其他 6 张表 (agents / email_logs / email_templates / bookings / bills / sos) 由
    # 上一条 migration 231db57b5b6f (init_schema) 创建, 这里不重复.
    op.create_table(
        'tracking_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('booking_id', sa.String(length=36), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'BOOKED', 'EMPTY_PICKED_UP', 'LOADED', 'DEPARTED', 'IN_TRANSIT',
                'ARRIVED', 'DELIVERED', 'COMPLETED', 'EXCEPTION',
                name='trackingstatus',
            ),
            nullable=False,
        ),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('location', sa.String(length=128), nullable=True),
        sa.Column('vessel_name', sa.String(length=128), nullable=True),
        sa.Column('voyage_no', sa.String(length=32), nullable=True),
        sa.Column('container_no', sa.String(length=32), nullable=True),
        sa.Column(
            'source',
            sa.Enum('AUTO', 'MANUAL', 'EMAIL', 'API', name='trackingsource'),
            nullable=False,
        ),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tracking_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tracking_events_booking_id'), ['booking_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tracking_events_status'), ['status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('tracking_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tracking_events_status'))
        batch_op.drop_index(batch_op.f('ix_tracking_events_booking_id'))

    op.drop_table('tracking_events')
