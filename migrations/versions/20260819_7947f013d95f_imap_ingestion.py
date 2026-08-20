"""imap ingestion

Revision ID: 7947f013d95f
Revises: 96634bd43325
Create Date: 2026-08-19 21:50:32.000000

v0.5 阶段 0 修: 这个 migration 原本是 alembic autogenerate 误生成的, 重复创建了
init_schema / bill_tracking 已有的 7 张表. v0.4 之前用 init_db() 部署, bug 没暴露.
v0.5 阶段 2 切到 alembic upgrade head 时会失败.

修复: 删掉重复 create_table, 只保留本 migration 真正新增的 2 张表:
- email_ingestions
- processed_emails
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7947f013d95f'
down_revision: Union[str, None] = '96634bd43325'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 本 migration 真正新增: email_ingestions + processed_emails.
    # 其他表由前序 migration 创建, 不重复.

    op.create_table(
        'email_ingestions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column(
            'source',
            sa.Enum('IMAP', 'MOCK', 'MANUAL', name='ingestionsource'),
            nullable=False,
        ),
        sa.Column('mailbox', sa.String(length=64), nullable=False),
        sa.Column(
            'status',
            sa.Enum('RUNNING', 'SUCCESS', 'FAILED', name='ingestionstatus'),
            nullable=False,
        ),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_fetched', sa.Integer(), nullable=False),
        sa.Column('new_count', sa.Integer(), nullable=False),
        sa.Column('skip_count', sa.Integer(), nullable=False),
        sa.Column('error_count', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('so_ids', sa.JSON(), nullable=False),
        sa.Column('skipped_message_ids', sa.JSON(), nullable=False),
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
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('email_ingestions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_ingestions_status'), ['status'], unique=False)

    op.create_table(
        'processed_emails',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('message_id', sa.String(length=255), nullable=False),
        sa.Column('message_id_hash', sa.String(length=64), nullable=False),
        sa.Column('from_addr', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'source',
            sa.Enum('IMAP', 'MOCK', 'MANUAL', name='ingestionsource'),
            nullable=False,
        ),
        sa.Column('so_id', sa.String(length=36), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ingestion_id', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['so_id'], ['sos.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ingestion_id'], ['email_ingestions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('processed_emails', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_processed_emails_received'), ['received_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_processed_emails_message_id'), ['message_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_processed_emails_message_id_hash'), ['message_id_hash'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('processed_emails', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_processed_emails_message_id_hash'))
        batch_op.drop_index(batch_op.f('ix_processed_emails_message_id'))
        batch_op.drop_index(batch_op.f('ix_processed_emails_received'))

    op.drop_table('processed_emails')
    with op.batch_alter_table('email_ingestions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_ingestions_status'))

    op.drop_table('email_ingestions')
