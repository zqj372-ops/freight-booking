"""v0_5_8_bill_v5_doc_status

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-20 18:30:00.000000

v0.5 阶段 1.5.5: Bill v0.5 model + Document 状态机字段
- bills_v5 新表 (独立于 v0.4 bills, 用于 v0.5 业务)
- documents.status 字段 (4 态: pending/uploaded/matched/archived)
- documents.archived_at + archived_by
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Document 加 status 字段 (4 态, 用 String(32) 不用 Enum 避免 check constraint)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    doc_cols = [c['name'] for c in inspector.get_columns('documents')] if 'documents' in inspector.get_table_names() else []
    if 'status' not in doc_cols:
        op.add_column('documents', sa.Column('status', sa.String(length=32), nullable=False, server_default='uploaded'))
        op.add_column('documents', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
        op.add_column('documents', sa.Column('archived_by', sa.String(length=36), nullable=True))
        op.create_index('ix_documents_status', 'documents', ['status'])

    # 2. Bill v0.5 新表 bills_v5
    if 'bills_v5' not in inspector.get_table_names():
        op.create_table(
            'bills_v5',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('bill_no', sa.String(length=64), nullable=False),
            sa.Column('bill_type', sa.String(length=16), nullable=False, server_default='receivable'),
            sa.Column('bill_kind', sa.String(length=32), nullable=False, server_default='other'),
            sa.Column('shipment_id', sa.String(length=36), nullable=True),
            sa.Column('matched_shipment_id', sa.String(length=36), nullable=True),
            sa.Column('seller_name', sa.String(length=255), nullable=True),
            sa.Column('seller_tax_no', sa.String(length=64), nullable=True),
            sa.Column('buyer_name', sa.String(length=255), nullable=True),
            sa.Column('buyer_tax_no', sa.String(length=64), nullable=True),
            sa.Column('currency', sa.String(length=8), nullable=False, server_default='CNY'),
            sa.Column('total_amount', sa.Float(), nullable=True),
            sa.Column('tax_amount', sa.Float(), nullable=True),
            sa.Column('amount_excl_tax', sa.Float(), nullable=True),
            sa.Column('file_path', sa.String(length=500), nullable=True),
            sa.Column('file_name', sa.String(length=255), nullable=True),
            sa.Column('file_mime', sa.String(length=128), nullable=True),
            sa.Column('file_size', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('ocr_text', sa.Text(), nullable=True),
            sa.Column('ocr_engine', sa.String(length=32), nullable=True),
            sa.Column('ocr_confidence', sa.Float(), nullable=True),
            sa.Column('ocr_error', sa.Text(), nullable=True),
            sa.Column('ocr_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('line_items', sa.JSON(), nullable=False, server_default='[]'),
            sa.Column('extra_fields', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='uploaded'),
            sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('matched_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('match_score', sa.Float(), nullable=True),
            sa.Column('payment_method', sa.String(length=32), nullable=True),
            sa.Column('payment_ref', sa.String(length=128), nullable=True),
            sa.Column('payment_proof_status', sa.String(length=32), nullable=True),
            sa.Column('payment_proof_uploaded_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('payment_proof_uploaded_by', sa.String(length=36), nullable=True),
            sa.Column('remark', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_bills_v5_organization'),
            sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], name='fk_bills_v5_shipment'),
            sa.ForeignKeyConstraint(['matched_shipment_id'], ['shipments.id'], name='fk_bills_v5_matched_shipment'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_bills_v5_bill_no', 'bills_v5', ['bill_no'])
        op.create_index('ix_bills_v5_shipment_id', 'bills_v5', ['shipment_id'])
        op.create_index('ix_bills_v5_matched_shipment_id', 'bills_v5', ['matched_shipment_id'])
        op.create_index('ix_bills_v5_organization_id', 'bills_v5', ['organization_id'])
        op.create_index('ix_bills_v5_org_status', 'bills_v5', ['organization_id', 'status'])
        op.create_index('ix_bills_v5_org_due', 'bills_v5', ['organization_id', 'due_at'])


def downgrade() -> None:
    op.drop_table('bills_v5')
    op.drop_index('ix_documents_status', table_name='documents')
    op.drop_column('documents', 'archived_by')
    op.drop_column('documents', 'archived_at')
    op.drop_column('documents', 'status')
