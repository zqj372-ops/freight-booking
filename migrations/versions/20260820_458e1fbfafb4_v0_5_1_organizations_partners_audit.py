"""v0_5_1_organizations_partners_audit

Revision ID: 458e1fbfafb4
Revises: 999c813c4675
Create Date: 2026-08-20 10:48:48.379104

v0.5 阶段 1.1: 创建 organizations / partners / audit_logs 三张表
- organizations: 业务编号规则配置 (单租户 seed default-company)
- partners: 替代 v0.4 agents, 扩展 partner_type / preferred_routes / response_sla
- audit_logs: 所有写操作审计 (v0.5 从上线日清零, 不回填 v0.4 历史)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '458e1fbfafb4'
down_revision: Union[str, None] = '999c813c4675'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === organizations ===
    op.create_table(
        'organizations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('job_no_prefix', sa.String(length=8), nullable=False, server_default='FB'),
        sa.Column('job_no_date_fmt', sa.String(length=16), nullable=False, server_default='YYYYMMDD'),
        sa.Column('job_no_seq_digits', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('job_no_reset_policy',
                  sa.Enum('daily', 'monthly', 'never', name='jobnoresetpolicy'),
                  nullable=False, server_default='daily'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', name='uq_organizations_slug'),
    )
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=True)

    # === partners ===
    op.create_table(
        'partners',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('partner_type',
                  sa.Enum('customer', 'carrier', 'agent_l1', 'agent_l2',
                          'trucking', 'warehouse', 'customs_broker',
                          name='partnertype'),
                  nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('short_code', sa.String(length=64), nullable=True),
        sa.Column('primary_email', sa.String(length=255), nullable=True),
        sa.Column('cc_emails', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('contact_person', sa.String(length=64), nullable=True),
        sa.Column('contact_phone', sa.String(length=32), nullable=True),
        sa.Column('contact_wechat', sa.String(length=64), nullable=True),
        sa.Column('preferred_routes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('preferred_carriers', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('response_sla_hours', sa.Integer(), nullable=True),
        sa.Column('default_template_id', sa.String(length=36), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_partners_organization'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'short_code', name='uq_partners_org_short_code'),
    )
    op.create_index('ix_partners_organization_id', 'partners', ['organization_id'])
    op.create_index('ix_partners_partner_type', 'partners', ['partner_type'])
    op.create_index('ix_partners_name', 'partners', ['name'])
    op.create_index('ix_partners_primary_email', 'partners', ['primary_email'])
    op.create_index('ix_partners_is_active', 'partners', ['is_active'])
    op.create_index('ix_partners_org_type', 'partners', ['organization_id', 'partner_type'])
    op.create_index('ix_partners_org_name', 'partners', ['organization_id', 'name'])

    # === audit_logs ===
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=False),
        sa.Column('entity_id', sa.String(length=36), nullable=False),
        sa.Column('action',
                  sa.Enum('create', 'update', 'delete', 'stage_change', 'cancel',
                          'accept', 'reject', 'send', 'match', 'upload', 'ocr_done',
                          'resolve', 'auto_close', 'record',
                          name='auditaction'),
                  nullable=False),
        sa.Column('actor_type',
                  sa.Enum('user', 'system', 'scheduled_job', 'api', name='auditactortype'),
                  nullable=False, server_default='api'),
        sa.Column('actor_user_id', sa.String(length=36), nullable=True),
        sa.Column('actor_user_name', sa.String(length=128), nullable=True),
        sa.Column('actor_job_name', sa.String(length=64), nullable=True),
        sa.Column('field_changes', sa.JSON(), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_audit_logs_organization'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_organization_id', 'audit_logs', ['organization_id'])
    op.create_index('ix_audit_logs_entity_type', 'audit_logs', ['entity_type'])
    op.create_index('ix_audit_logs_entity_id', 'audit_logs', ['entity_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_actor_user_id', 'audit_logs', ['actor_user_id'])
    op.create_index('ix_audit_org_entity', 'audit_logs', ['organization_id', 'entity_type', 'entity_id'])
    op.create_index('ix_audit_org_action_time', 'audit_logs', ['organization_id', 'action', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_audit_org_action_time', table_name='audit_logs')
    op.drop_index('ix_audit_org_entity', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_user_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_index('ix_audit_logs_entity_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_entity_type', table_name='audit_logs')
    op.drop_index('ix_audit_logs_organization_id', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.execute("DROP TYPE IF EXISTS auditactortype")
    op.execute("DROP TYPE IF EXISTS auditaction")

    op.drop_index('ix_partners_org_name', table_name='partners')
    op.drop_index('ix_partners_org_type', table_name='partners')
    op.drop_index('ix_partners_is_active', table_name='partners')
    op.drop_index('ix_partners_primary_email', table_name='partners')
    op.drop_index('ix_partners_name', table_name='partners')
    op.drop_index('ix_partners_partner_type', table_name='partners')
    op.drop_index('ix_partners_organization_id', table_name='partners')
    op.drop_table('partners')
    op.execute("DROP TYPE IF EXISTS partnertype")

    op.drop_index('ix_organizations_slug', table_name='organizations')
    op.drop_table('organizations')
    op.execute("DROP TYPE IF EXISTS jobnoresetpolicy")
