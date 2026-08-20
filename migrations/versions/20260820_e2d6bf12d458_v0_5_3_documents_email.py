"""v0_5_3_documents_email

Revision ID: e2d6bf12d458
Revises: d272a4d852d8
Create Date: 2026-08-20 11:14:00.000000

v0.5 阶段 1.3: 文件 + 邮件
- documents (inbound/outbound/手动上传的文件)
- document_extractions (OCR/regex 抽取结果, 与 Document 解耦)
- email_threads (聚合一组邮件)
- email_messages (单封邮件, inbound/outbound)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2d6bf12d458'
down_revision: Union[str, None] = 'd272a4d852d8'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === documents ===
    op.create_table(
        'documents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('shipment_id', sa.String(length=36), nullable=True),
        sa.Column('booking_request_id', sa.String(length=36), nullable=True),
        sa.Column('booking_confirmation_id', sa.String(length=36), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=False),
        sa.Column('mime_type', sa.String(length=128), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'source',
            sa.Enum('imap_attachment', 'manual_upload', 'generated', name='documentsource'),
            nullable=False,
        ),
        sa.Column('source_message_id', sa.String(length=36), nullable=True),
        sa.Column('source_account_id', sa.String(length=36), nullable=True),
        sa.Column(
            'doc_type',
            sa.Enum('so', 'bl', 'invoice', 'si', 'vgm', 'packing_list', 'other', name='documenttype'),
            nullable=False, server_default='other',
        ),
        sa.Column('carrier_hint', sa.String(length=64), nullable=True),
        sa.Column(
            'ocr_status',
            sa.Enum('pending', 'processing', 'done', 'failed', name='ocrstatus'),
            nullable=False, server_default='pending',
        ),
        sa.Column('ocr_text', sa.Text(), nullable=True),
        sa.Column('ocr_engine', sa.String(length=32), nullable=True),
        sa.Column('ocr_confidence', sa.Float(), nullable=True),
        sa.Column('ocr_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ocr_error', sa.Text(), nullable=True),
        sa.Column(
            'parse_status',
            sa.Enum('unmatched', 'matched_shipment', 'matched_booking', 'ignored', name='parsestatus'),
            nullable=False, server_default='unmatched',
        ),
        sa.Column('parse_confidence', sa.Float(), nullable=True),
        sa.Column('uploaded_by', sa.String(length=36), nullable=True),
        sa.Column('uploaded_by_name', sa.String(length=128), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_documents_organization'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_documents_organization_id', 'documents', ['organization_id'])
    op.create_index('ix_documents_shipment_id', 'documents', ['shipment_id'])
    op.create_index('ix_documents_booking_request_id', 'documents', ['booking_request_id'])
    op.create_index('ix_documents_booking_confirmation_id', 'documents', ['booking_confirmation_id'])
    op.create_index('ix_documents_file_hash', 'documents', ['file_hash'])
    op.create_index('ix_documents_source', 'documents', ['source'])
    op.create_index('ix_documents_doc_type', 'documents', ['doc_type'])
    op.create_index('ix_documents_carrier_hint', 'documents', ['carrier_hint'])
    op.create_index('ix_documents_ocr_status', 'documents', ['ocr_status'])
    op.create_index('ix_documents_parse_status', 'documents', ['parse_status'])
    op.create_index('uq_documents_org_file_hash', 'documents', ['organization_id', 'file_hash'], unique=True)
    op.create_index('ix_documents_org_doc_type', 'documents', ['organization_id', 'doc_type'])

    # === document_extractions ===
    op.create_table(
        'document_extractions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('document_id', sa.String(length=36), nullable=False),
        sa.Column(
            'extraction_method',
            sa.Enum('regex', 'pdf_text', 'ocr', 'llm', 'manual', name='extractionmethod'),
            nullable=False,
        ),
        sa.Column('fields', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('diff', sa.JSON(), nullable=True),
        sa.Column('model_version', sa.String(length=64), nullable=True),
        sa.Column('raw_response', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_document_extractions_organization'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_document_extractions_organization_id', 'document_extractions', ['organization_id'])
    op.create_index('ix_document_extractions_document_id', 'document_extractions', ['document_id'])
    op.create_index('ix_extractions_org_doc', 'document_extractions', ['organization_id', 'document_id'])

    # === email_threads ===
    op.create_table(
        'email_threads',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('subject_prefix', sa.String(length=64), nullable=True),
        sa.Column('shipment_id', sa.String(length=36), nullable=True),
        sa.Column('booking_request_id', sa.String(length=36), nullable=True),
        sa.Column('partner_id', sa.String(length=36), nullable=True),
        sa.Column(
            'status',
            sa.Enum('active', 'closed', 'spam', name='emailthreadstatus'),
            nullable=False, server_default='active',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_email_threads_organization'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_email_threads_organization_id', 'email_threads', ['organization_id'])
    op.create_index('ix_email_threads_subject_prefix', 'email_threads', ['subject_prefix'])
    op.create_index('ix_email_threads_shipment_id', 'email_threads', ['shipment_id'])
    op.create_index('ix_email_threads_booking_request_id', 'email_threads', ['booking_request_id'])
    op.create_index('ix_email_threads_partner_id', 'email_threads', ['partner_id'])
    op.create_index('ix_email_threads_status', 'email_threads', ['status'])
    op.create_index('ix_email_threads_org_status', 'email_threads', ['organization_id', 'status'])

    # === email_messages ===
    op.create_table(
        'email_messages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('thread_id', sa.String(length=36), nullable=False),
        sa.Column(
            'direction',
            sa.Enum('inbound', 'outbound', name='emaildirection'),
            nullable=False,
        ),
        sa.Column('message_id', sa.String(length=255), nullable=True),
        sa.Column('in_reply_to', sa.String(length=255), nullable=True),
        sa.Column('references', sa.Text(), nullable=True),
        sa.Column('from_addr', sa.String(length=255), nullable=False),
        sa.Column('to_addrs', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('cc_addrs', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('body_html', sa.Text(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'status',
            sa.Enum(
                'draft', 'queued', 'sent', 'failed', 'received',
                'processing', 'processed', 'ignored',
                name='emailmessagestatus',
            ),
            nullable=False, server_default='draft',
        ),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'source',
            sa.Enum('smtp_send', 'imap_poll', 'manual', name='emailsource'),
            nullable=False, server_default='manual',
        ),
        sa.Column('raw_eml_path', sa.String(length=500), nullable=True),
        sa.Column('matched_shipment_id', sa.String(length=36), nullable=True),
        sa.Column('matched_booking_request_id', sa.String(length=36), nullable=True),
        sa.Column('match_confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_email_messages_organization'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_email_messages_organization_id', 'email_messages', ['organization_id'])
    op.create_index('ix_email_messages_thread_id', 'email_messages', ['thread_id'])
    op.create_index('ix_email_messages_direction', 'email_messages', ['direction'])
    op.create_index('ix_email_messages_message_id', 'email_messages', ['message_id'], unique=True)
    op.create_index('ix_email_messages_from_addr', 'email_messages', ['from_addr'])
    op.create_index('ix_email_messages_received_at', 'email_messages', ['received_at'])
    op.create_index('ix_email_messages_status', 'email_messages', ['status'])
    op.create_index('ix_email_messages_matched_shipment_id', 'email_messages', ['matched_shipment_id'])
    op.create_index('ix_email_messages_org_status', 'email_messages', ['organization_id', 'status'])
    op.create_index('ix_email_messages_thread', 'email_messages', ['thread_id'])


def downgrade() -> None:
    op.drop_index('ix_email_messages_thread', table_name='email_messages')
    op.drop_index('ix_email_messages_org_status', table_name='email_messages')
    op.drop_index('ix_email_messages_matched_shipment_id', table_name='email_messages')
    op.drop_index('ix_email_messages_status', table_name='email_messages')
    op.drop_index('ix_email_messages_received_at', table_name='email_messages')
    op.drop_index('ix_email_messages_from_addr', table_name='email_messages')
    op.drop_index('ix_email_messages_message_id', table_name='email_messages')
    op.drop_index('ix_email_messages_direction', table_name='email_messages')
    op.drop_index('ix_email_messages_thread_id', table_name='email_messages')
    op.drop_index('ix_email_messages_organization_id', table_name='email_messages')
    op.drop_table('email_messages')
    op.execute("DROP TYPE IF EXISTS emailsource")
    op.execute("DROP TYPE IF EXISTS emailmessagestatus")
    op.execute("DROP TYPE IF EXISTS emaildirection")

    op.drop_index('ix_email_threads_org_status', table_name='email_threads')
    op.drop_index('ix_email_threads_status', table_name='email_threads')
    op.drop_index('ix_email_threads_partner_id', table_name='email_threads')
    op.drop_index('ix_email_threads_booking_request_id', table_name='email_threads')
    op.drop_index('ix_email_threads_shipment_id', table_name='email_threads')
    op.drop_index('ix_email_threads_subject_prefix', table_name='email_threads')
    op.drop_index('ix_email_threads_organization_id', table_name='email_threads')
    op.drop_table('email_threads')
    op.execute("DROP TYPE IF EXISTS emailthreadstatus")

    op.drop_index('ix_extractions_org_doc', table_name='document_extractions')
    op.drop_index('ix_document_extractions_document_id', table_name='document_extractions')
    op.drop_index('ix_document_extractions_organization_id', table_name='document_extractions')
    op.drop_table('document_extractions')
    op.execute("DROP TYPE IF EXISTS extractionmethod")

    op.drop_index('ix_documents_org_doc_type', table_name='documents')
    op.drop_index('uq_documents_org_file_hash', table_name='documents')
    op.drop_index('ix_documents_parse_status', table_name='documents')
    op.drop_index('ix_documents_ocr_status', table_name='documents')
    op.drop_index('ix_documents_carrier_hint', table_name='documents')
    op.drop_index('ix_documents_doc_type', table_name='documents')
    op.drop_index('ix_documents_source', table_name='documents')
    op.drop_index('ix_documents_file_hash', table_name='documents')
    op.drop_index('ix_documents_booking_confirmation_id', table_name='documents')
    op.drop_index('ix_documents_booking_request_id', table_name='documents')
    op.drop_index('ix_documents_shipment_id', table_name='documents')
    op.drop_index('ix_documents_organization_id', table_name='documents')
    op.drop_table('documents')
    op.execute("DROP TYPE IF EXISTS parsestatus")
    op.execute("DROP TYPE IF EXISTS ocrstatus")
    op.execute("DROP TYPE IF EXISTS documenttype")
    op.execute("DROP TYPE IF EXISTS documentsource")
