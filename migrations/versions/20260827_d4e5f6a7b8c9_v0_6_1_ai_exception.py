"""v0_6_1_ai_exception

Revision ID: d4e5f6a7b8c9
Revises: c97d5e8f4a1b
Create Date: 2026-08-27 13:36:00.000000

v0.6 阶段 1: 异常 AI 跟进
- exception_updates 新表 (跟进 timeline: AI 抓取/用户备注/LLM 摘要/状态变更/AI 建议)
- exception_fetch_jobs 新表 (后台抓取任务: carrier 网站/邮件/企微)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c97d5e8f4a1b'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. exception_updates
    op.create_table(
        'exception_updates',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('exception_id', sa.String(length=36), nullable=False),
        sa.Column('update_type', sa.String(length=32), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('ai_model', sa.String(length=64), nullable=True),
        sa.Column('ai_confidence', sa.Float(), nullable=True),
        sa.Column('created_by_type', sa.String(length=16), nullable=False, server_default='ai'),
        sa.Column('created_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('created_by_user_name', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['exception_id'], ['operational_exceptions.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_exception_updates_organization_id', 'exception_updates', ['organization_id'])
    op.create_index('ix_exception_updates_exception_id', 'exception_updates', ['exception_id'])
    op.create_index('ix_exception_updates_update_type', 'exception_updates', ['update_type'])
    op.create_index('ix_exception_updates_org_exception', 'exception_updates', ['organization_id', 'exception_id'])

    # 2. exception_fetch_jobs
    op.create_table(
        'exception_fetch_jobs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('exception_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_runs', sa.Integer(), nullable=False, server_default='84'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['exception_id'], ['operational_exceptions.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_exception_fetch_jobs_organization_id', 'exception_fetch_jobs', ['organization_id'])
    op.create_index('ix_exception_fetch_jobs_exception_id', 'exception_fetch_jobs', ['exception_id'])
    op.create_index('ix_exception_fetch_jobs_status', 'exception_fetch_jobs', ['status'])
    op.create_index('ix_exception_fetch_jobs_next_run_at', 'exception_fetch_jobs', ['next_run_at'])
    op.create_index('ix_exception_fetch_jobs_org_status_next', 'exception_fetch_jobs',
                    ['organization_id', 'status', 'next_run_at'])


def downgrade() -> None:
    op.drop_index('ix_exception_fetch_jobs_org_status_next', table_name='exception_fetch_jobs')
    op.drop_index('ix_exception_fetch_jobs_next_run_at', table_name='exception_fetch_jobs')
    op.drop_index('ix_exception_fetch_jobs_status', table_name='exception_fetch_jobs')
    op.drop_index('ix_exception_fetch_jobs_exception_id', table_name='exception_fetch_jobs')
    op.drop_index('ix_exception_fetch_jobs_organization_id', table_name='exception_fetch_jobs')
    op.drop_table('exception_fetch_jobs')

    op.drop_index('ix_exception_updates_org_exception', table_name='exception_updates')
    op.drop_index('ix_exception_updates_update_type', table_name='exception_updates')
    op.drop_index('ix_exception_updates_exception_id', table_name='exception_updates')
    op.drop_index('ix_exception_updates_organization_id', table_name='exception_updates')
    op.drop_table('exception_updates')
