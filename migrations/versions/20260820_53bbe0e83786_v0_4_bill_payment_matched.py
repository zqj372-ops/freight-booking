"""v0.4 bill payment + matched

Revision ID: 53bbe0e83786
Revises: 7947f013d95f
Create Date: 2026-08-20 00:23:56.428774

v0.5 阶段 0 修: 原本是 alembic autogenerate 误生成, 重复创建了 9 张已存在的表.
真正的目的是给 bills 表加 v0.4 财务字段:
- matched_booking_id
- matched_at
- match_score
- payment_method
- payment_ref

修复: 删掉重复 create_table, 只 add_column 给 bills.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53bbe0e83786'
down_revision: Union[str, None] = '7947f013d95f'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 给 bills 加 v0.4 财务对账字段
    with op.batch_alter_table('bills', schema=None) as batch_op:
        batch_op.add_column(sa.Column('matched_booking_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('matched_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('match_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('payment_method', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('payment_ref', sa.String(length=128), nullable=True))
        batch_op.create_index(batch_op.f('ix_bills_matched_booking_id'), ['matched_booking_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_bills_matched_booking_id', 'bookings',
            ['matched_booking_id'], ['id'], ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('bills', schema=None) as batch_op:
        batch_op.drop_constraint('fk_bills_matched_booking_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_bills_matched_booking_id'))
        batch_op.drop_column('payment_ref')
        batch_op.drop_column('payment_method')
        batch_op.drop_column('match_score')
        batch_op.drop_column('matched_at')
        batch_op.drop_column('matched_booking_id')
