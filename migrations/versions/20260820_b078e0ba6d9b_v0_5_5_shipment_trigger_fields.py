"""v0_5_5_shipment_trigger_fields

Revision ID: b078e0ba6d9b
Revises: af032b210771
Create Date: 2026-08-20 11:55:00.000000

v0.5 阶段 1.5: Shipment 触发字段 (11 个时间戳, 来自 Excel 18 个新增字段)
- customer_name (来自客户表冗余, 单独保留)
- booking_request_sent_at, so_received_at, si_info_ready_at, bl_draft_received_at
- sealed_at, cy_open_at, si_cutoff_at, vgm_cutoff_at, cy_cutoff_at
- empty_return_due_at, last_updated_at
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b078e0ba6d9b'
down_revision: Union[str, None] = 'af032b210771'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 客户名称 (冗余, 用于搜索和快速展示)
    op.add_column('shipments', sa.Column('customer_name', sa.String(length=255), nullable=True))
    op.create_index('ix_shipments_customer_name', 'shipments', ['customer_name'])

    # 17 SLA 触发字段 (本次先加 11 个关键时间戳)
    op.add_column('shipments', sa.Column('booking_request_sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('so_received_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('si_info_ready_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('bl_draft_received_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('sealed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('cy_open_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('si_cutoff_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('vgm_cutoff_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('cy_cutoff_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('empty_return_due_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shipments', sa.Column('last_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('shipments', 'last_updated_at')
    op.drop_column('shipments', 'empty_return_due_at')
    op.drop_column('shipments', 'cy_cutoff_at')
    op.drop_column('shipments', 'vgm_cutoff_at')
    op.drop_column('shipments', 'si_cutoff_at')
    op.drop_column('shipments', 'cy_open_at')
    op.drop_column('shipments', 'sealed_at')
    op.drop_column('shipments', 'bl_draft_received_at')
    op.drop_column('shipments', 'si_info_ready_at')
    op.drop_column('shipments', 'so_received_at')
    op.drop_column('shipments', 'booking_request_sent_at')
    op.drop_index('ix_shipments_customer_name', table_name='shipments')
    op.drop_column('shipments', 'customer_name')
