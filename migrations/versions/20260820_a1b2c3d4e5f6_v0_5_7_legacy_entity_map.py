"""v0_5_7_legacy_entity_map

Revision ID: a1b2c3d4e5f6
Revises: 98f36e0c2693
Create Date: 2026-08-20 12:15:00.000000

v0.5 阶段 2: LegacyEntityMap 表 (v0.4 → v0.5 实体映射)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '98f36e0c2693'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 检查表是否已存在 (dev mode 已被 Base.metadata.create_all 重建)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'legacy_entity_maps' in inspector.get_table_names():
        return  # 表已存在, 跳过 (幂等)
    op.create_table(
        'legacy_entity_maps',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('v04_type', sa.String(length=32), nullable=False),
        sa.Column('v04_id', sa.String(length=36), nullable=False),
        sa.Column('v05_type', sa.String(length=32), nullable=False),
        sa.Column('v05_id', sa.String(length=36), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('mapped_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_legacy_maps_organization'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_legacy_entity_maps_organization_id', 'legacy_entity_maps', ['organization_id'])
    op.create_index('ix_legacy_entity_maps_v04_type', 'legacy_entity_maps', ['v04_type'])
    op.create_index('ix_legacy_entity_maps_v04_id', 'legacy_entity_maps', ['v04_id'])
    op.create_index('ix_legacy_entity_maps_v05_type', 'legacy_entity_maps', ['v05_type'])
    op.create_index('ix_legacy_entity_maps_v05_id', 'legacy_entity_maps', ['v05_id'])
    op.create_index('uq_legacy_map_v04_v05', 'legacy_entity_maps', ['organization_id', 'v04_type', 'v04_id', 'v05_type'], unique=True)
    op.create_index('ix_legacy_map_v05', 'legacy_entity_maps', ['organization_id', 'v05_type', 'v05_id'])


def downgrade() -> None:
    op.drop_index('ix_legacy_map_v05', table_name='legacy_entity_maps')
    op.drop_index('uq_legacy_map_v04_v05', table_name='legacy_entity_maps')
    op.drop_index('ix_legacy_entity_maps_v05_id', table_name='legacy_entity_maps')
    op.drop_index('ix_legacy_entity_maps_v05_type', table_name='legacy_entity_maps')
    op.drop_index('ix_legacy_entity_maps_v04_id', table_name='legacy_entity_maps')
    op.drop_index('ix_legacy_entity_maps_v04_type', table_name='legacy_entity_maps')
    op.drop_index('ix_legacy_entity_maps_organization_id', table_name='legacy_entity_maps')
    op.drop_table('legacy_entity_maps')
