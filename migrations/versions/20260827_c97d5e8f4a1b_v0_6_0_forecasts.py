"""v0_6_0_forecasts

Revision ID: c97d5e8f4a1b
Revises: b2c3d4e5f6a7
Create Date: 2026-08-27 12:30:00.000000

v0.6 阶段 0: 预报货量统计
- forecasts 新表 (v0.6 货量统计的入口表)
- 解决 4 源预报 (物友销售/客服/深鼎/分子公司) dedup
- 字段: source + source_ref (同源 UNIQUE) + content_fingerprint (跨源 dedup)
- status 5 态: forecasted/confirmed/allocated/loaded/cancelled
- shipment_id FK→shipments (配载关联)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c97d5e8f4a1b'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'forecasts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('source_ref', sa.String(length=128), nullable=True),
        sa.Column('content_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('customer_id', sa.String(length=36), nullable=False),
        sa.Column('customer_name', sa.String(length=255), nullable=False),
        sa.Column('pol', sa.String(length=64), nullable=False),
        sa.Column('pod', sa.String(length=64), nullable=False),
        sa.Column('container_type', sa.String(length=16), nullable=False, server_default='40HQ'),
        sa.Column('container_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('target_etd', sa.Date(), nullable=False),
        sa.Column('commodity', sa.String(length=255), nullable=True),
        sa.Column('weight_kg', sa.Float(), nullable=True),
        sa.Column('volume_cbm', sa.Float(), nullable=True),
        sa.Column('pieces', sa.Integer(), nullable=True),
        sa.Column('is_dangerous', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='forecasted'),
        sa.Column('shipment_id', sa.String(length=36), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('source_metadata', sa.JSON(), nullable=True),
        sa.Column('created_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('created_by_user_name', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['customer_id'], ['partners.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_forecasts_organization_id', 'forecasts', ['organization_id'])
    op.create_index('ix_forecasts_source', 'forecasts', ['source'])
    op.create_index('ix_forecasts_source_ref', 'forecasts', ['source_ref'])
    op.create_index('ix_forecasts_content_fingerprint', 'forecasts', ['content_fingerprint'])
    op.create_index('ix_forecasts_customer_id', 'forecasts', ['customer_id'])
    op.create_index('ix_forecasts_pol', 'forecasts', ['pol'])
    op.create_index('ix_forecasts_pod', 'forecasts', ['pod'])
    op.create_index('ix_forecasts_target_etd', 'forecasts', ['target_etd'])
    op.create_index('ix_forecasts_status', 'forecasts', ['status'])
    op.create_index('ix_forecasts_shipment_id', 'forecasts', ['shipment_id'])
    op.create_index('ix_forecasts_org_target_etd', 'forecasts', ['organization_id', 'target_etd'])
    op.create_index('ix_forecasts_org_route', 'forecasts', ['organization_id', 'pol', 'pod'])
    op.create_index('ix_forecasts_org_fingerprint', 'forecasts', ['organization_id', 'content_fingerprint'])
    # 同源同 source_ref UNIQUE (避免同源重复导入)
    op.create_index(
        'uq_forecasts_org_source_ref', 'forecasts',
        ['organization_id', 'source', 'source_ref'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_forecasts_org_source_ref', table_name='forecasts')
    op.drop_index('ix_forecasts_org_fingerprint', table_name='forecasts')
    op.drop_index('ix_forecasts_org_route', table_name='forecasts')
    op.drop_index('ix_forecasts_org_target_etd', table_name='forecasts')
    op.drop_index('ix_forecasts_shipment_id', table_name='forecasts')
    op.drop_index('ix_forecasts_status', table_name='forecasts')
    op.drop_index('ix_forecasts_target_etd', table_name='forecasts')
    op.drop_index('ix_forecasts_pod', table_name='forecasts')
    op.drop_index('ix_forecasts_pol', table_name='forecasts')
    op.drop_index('ix_forecasts_customer_id', table_name='forecasts')
    op.drop_index('ix_forecasts_content_fingerprint', table_name='forecasts')
    op.drop_index('ix_forecasts_source_ref', table_name='forecasts')
    op.drop_index('ix_forecasts_source', table_name='forecasts')
    op.drop_index('ix_forecasts_organization_id', table_name='forecasts')
    op.drop_table('forecasts')
