"""v0_6_3_transit_time

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-27 19:58:00.000000

v0.6.3 头程时效:
- eta_updates 新表 (每次 Shipment.eta 变更记一行)
- 3 个新 ExceptionCode: ETA_DELAYED / ETA_PASSED_UNLOADED / ETA_PASSED_DELIVERED
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str, None], None] = None


def upgrade() -> None:
    # 1. eta_updates
    op.create_table(
        'eta_updates',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('shipment_id', sa.String(length=36), nullable=False),
        sa.Column('old_eta', sa.Date(), nullable=True),
        sa.Column('new_eta', sa.Date(), nullable=False),
        sa.Column('delta_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('reason', sa.String(length=32), nullable=False, server_default='other'),
        sa.Column('change_reason', sa.Text(), nullable=True),
        sa.Column('related_document_id', sa.String(length=36), nullable=True),
        sa.Column('updated_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('updated_by_user_name', sa.String(length=128), nullable=True),
        sa.Column('triggered_exception_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_eta_updates_org_shipment', 'eta_updates', ['organization_id', 'shipment_id'])
    op.create_index('ix_eta_updates_shipment_id', 'eta_updates', ['shipment_id'])
    op.create_index('ix_eta_updates_shipment_created', 'eta_updates', ['shipment_id', 'created_at'])
    op.create_index('ix_eta_updates_source', 'eta_updates', ['source'])


def downgrade() -> None:
    op.drop_index('ix_eta_updates_source', table_name='eta_updates')
    op.drop_index('ix_eta_updates_shipment_created', table_name='eta_updates')
    op.drop_index('ix_eta_updates_shipment_id', table_name='eta_updates')
    op.drop_index('ix_eta_updates_org_shipment', table_name='eta_updates')
    op.drop_table('eta_updates')
