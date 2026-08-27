"""v0_6_2_checklist

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-27 15:40:00.000000

v0.6.2 清单复核:
- checklist_reviews 新表 (复核任务: 装船前/截关前/开船前/任意时刻)
- checklist_items 新表 (4 大类 14 项: 柜号/封条/柜型/件数/重量/体积/HS/危险品/超大件/4 文件齐套)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str, None], None] = None


def upgrade() -> None:
    # 1. checklist_reviews
    op.create_table(
        'checklist_reviews',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('shipment_id', sa.String(length=36), nullable=False),
        sa.Column('review_type', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='draft'),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('signed_off_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('reviewed_by_user_name', sa.String(length=128), nullable=True),
        sa.Column('total_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('passed_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('warning_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('critical_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('overall_severity', sa.String(length=16), nullable=False, server_default='pass'),
        sa.Column('trigger_reason', sa.Text(), nullable=True),
        sa.Column('related_exception_ids', sa.JSON(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('shipment_snapshot', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_checklist_reviews_org_shipment', 'checklist_reviews', ['organization_id', 'shipment_id'])
    op.create_index('ix_checklist_reviews_shipment_id', 'checklist_reviews', ['shipment_id'])
    op.create_index('ix_checklist_reviews_review_type', 'checklist_reviews', ['review_type'])
    op.create_index('ix_checklist_reviews_status', 'checklist_reviews', ['status'])

    # 2. checklist_items
    op.create_table(
        'checklist_items',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('review_id', sa.String(length=36), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('label', sa.String(length=128), nullable=False),
        sa.Column('expected_value', sa.String(length=256), nullable=True),
        sa.Column('actual_value', sa.String(length=256), nullable=True),
        sa.Column('match', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('severity', sa.String(length=16), nullable=False),
        sa.Column('delta', sa.Float(), nullable=True),
        sa.Column('delta_pct', sa.Float(), nullable=True),
        sa.Column('related_document_id', sa.String(length=36), nullable=True),
        sa.Column('related_container_id', sa.String(length=36), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('acknowledged_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['review_id'], ['checklist_reviews.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_checklist_items_review_id', 'checklist_items', ['review_id'])
    op.create_index('ix_checklist_items_code', 'checklist_items', ['code'])
    op.create_index('ix_checklist_items_category', 'checklist_items', ['category'])
    op.create_index('ix_checklist_items_org_severity', 'checklist_items', ['organization_id', 'severity'])


def downgrade() -> None:
    op.drop_index('ix_checklist_items_org_severity', table_name='checklist_items')
    op.drop_index('ix_checklist_items_category', table_name='checklist_items')
    op.drop_index('ix_checklist_items_code', table_name='checklist_items')
    op.drop_index('ix_checklist_items_review_id', table_name='checklist_items')
    op.drop_table('checklist_items')

    op.drop_index('ix_checklist_reviews_status', table_name='checklist_reviews')
    op.drop_index('ix_checklist_reviews_review_type', table_name='checklist_reviews')
    op.drop_index('ix_checklist_reviews_shipment_id', table_name='checklist_reviews')
    op.drop_index('ix_checklist_reviews_org_shipment', table_name='checklist_reviews')
    op.drop_table('checklist_reviews')
