"""v0_5_6_shipment_status_remarks

Revision ID: 98f36e0c2693
Revises: b078e0ba6d9b
Create Date: 2026-08-20 12:00:00.000000

v0.5 阶段 1.5.2: Shipment Y/N → enum 状态 + 5 类备注拆分
- 7 个状态字段: customs_status, inspection_status, rolled_status, payment_request_status,
  payment_proof_status, empty_return_status, bl_process_status
- 2 个时间戳: customs_released_at, inspection_received_at
- 5 类备注: booking_remark, bl_remark, customs_remark, pod_remark, finance_remark
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98f36e0c2693'
down_revision: Union[str, None] = 'b078e0ba6d9b'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 5 类备注拆分
    op.add_column('shipments', sa.Column('booking_remark', sa.Text(), nullable=True))
    op.add_column('shipments', sa.Column('bl_remark', sa.Text(), nullable=True))
    op.add_column('shipments', sa.Column('customs_remark', sa.Text(), nullable=True))
    op.add_column('shipments', sa.Column('pod_remark', sa.Text(), nullable=True))
    op.add_column('shipments', sa.Column('finance_remark', sa.Text(), nullable=True))

    # 7 个 enum 状态字段 (用 String(32) 存 enum value, 不用 SQLAlchemy Enum 是为了 v0.5 灵活)
    op.add_column('shipments', sa.Column('customs_status', sa.String(length=32), nullable=True))
    op.add_column('shipments', sa.Column('inspection_status', sa.String(length=32), nullable=True))
    op.add_column('shipments', sa.Column('rolled_status', sa.String(length=32), nullable=True))
    op.add_column('shipments', sa.Column('payment_request_status', sa.String(length=32), nullable=True))
    op.add_column('shipments', sa.Column('payment_proof_status', sa.String(length=32), nullable=True))
    op.add_column('shipments', sa.Column('empty_return_status', sa.String(length=32), nullable=True))
    op.add_column('shipments', sa.Column('bl_process_status', sa.String(length=32), nullable=True))

    # 状态时间戳
    op.add_column('shipments', sa.Column('customs_released_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('customs_released_by', sa.String(length=128), nullable=True))
    op.add_column('shipments', sa.Column('inspection_received_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('shipments', 'inspection_received_at')
    op.drop_column('shipments', 'customs_released_by')
    op.drop_column('shipments', 'customs_released_at')

    op.drop_column('shipments', 'bl_process_status')
    op.drop_column('shipments', 'empty_return_status')
    op.drop_column('shipments', 'payment_proof_status')
    op.drop_column('shipments', 'payment_request_status')
    op.drop_column('shipments', 'rolled_status')
    op.drop_column('shipments', 'inspection_status')
    op.drop_column('shipments', 'customs_status')

    op.drop_column('shipments', 'finance_remark')
    op.drop_column('shipments', 'pod_remark')
    op.drop_column('shipments', 'customs_remark')
    op.drop_column('shipments', 'bl_remark')
    op.drop_column('shipments', 'booking_remark')
