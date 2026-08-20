"""v0_5_4_milestones_tasks_exceptions

Revision ID: af032b210771
Revises: e2d6bf12d458
Create Date: 2026-08-20 11:25:00.000000

v0.5 阶段 1.4: 状态分层
- milestones (业务节点, 不可变日志)
- tasks (待办, 可变, auto_close_on 字段)
- operational_exceptions (异常, 0..N, 状态 open/resolved/auto_closed)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'af032b210771'
down_revision: Union[str, None] = 'e2d6bf12d458'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === milestones ===
    op.create_table(
        'milestones',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('shipment_id', sa.String(length=36), nullable=False),
        sa.Column(
            'code',
            sa.Enum(
                'booking_request_sent', 'booking_request_acknowledged',
                'booking_confirmation_received', 'booking_confirmation_accepted',
                'booking_rejected', 'empty_release_available',
                'container_picked_up', 'container_gated_in', 'container_loaded',
                'si_submitted', 'vgm_submitted', 'customs_cleared',
                'si_cutoff_passed', 'vgm_cutoff_passed', 'cy_cutoff_passed',
                'gate_in', 'departed', 'arrived_at_pol', 'in_transit',
                'arrived_at_pod', 'customs_cleared_at_pod', 'container_discharged',
                'delivered', 'empty_returned',
                name='milestonecode',
            ),
            nullable=False,
        ),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'source',
            sa.Enum('auto', 'manual', 'email', 'api', name='milestonesource'),
            nullable=False, server_default='manual',
        ),
        sa.Column('source_ref', sa.String(length=128), nullable=True),
        sa.Column('location', sa.String(length=128), nullable=True),
        sa.Column('vessel_name', sa.String(length=128), nullable=True),
        sa.Column('voyage_no', sa.String(length=32), nullable=True),
        sa.Column('container_no', sa.String(length=32), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('corrected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('corrected_by', sa.String(length=36), nullable=True),
        sa.Column('corrected_milestone_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_milestones_organization'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], name='fk_milestones_shipment'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_milestones_organization_id', 'milestones', ['organization_id'])
    op.create_index('ix_milestones_shipment_id', 'milestones', ['shipment_id'])
    op.create_index('ix_milestones_code', 'milestones', ['code'])
    op.create_index('ix_milestones_org_shipment', 'milestones', ['organization_id', 'shipment_id'])
    op.create_index('ix_milestones_shipment_occurred', 'milestones', ['shipment_id', 'occurred_at'])

    # === tasks ===
    op.create_table(
        'tasks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('shipment_id', sa.String(length=36), nullable=False),
        sa.Column(
            'code',
            sa.Enum(
                'confirm_so', 'confirm_booking', 'contact_supplier',
                'arrange_pickup', 'record_container_no', 'record_seal_no',
                'submit_si', 'submit_vgm', 'confirm_cargo_ready',
                'confirm_loaded', 'handle_exception',
                name='taskcode',
            ),
            nullable=False,
        ),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('assignee_user_id', sa.String(length=36), nullable=True),
        sa.Column('assignee_user_name', sa.String(length=128), nullable=True),
        sa.Column(
            'status',
            sa.Enum('pending', 'in_progress', 'done', 'cancelled', name='taskstatus'),
            nullable=False, server_default='pending',
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by', sa.String(length=36), nullable=True),
        sa.Column('completed_by_name', sa.String(length=128), nullable=True),
        sa.Column('auto_close_on', sa.Enum(
            'booking_request_sent', 'booking_request_acknowledged',
            'booking_confirmation_received', 'booking_confirmation_accepted',
            'booking_rejected', 'empty_release_available',
            'container_picked_up', 'container_gated_in', 'container_loaded',
            'si_submitted', 'vgm_submitted', 'customs_cleared',
            'si_cutoff_passed', 'vgm_cutoff_passed', 'cy_cutoff_passed',
            'gate_in', 'departed', 'arrived_at_pol', 'in_transit',
            'arrived_at_pod', 'customs_cleared_at_pod', 'container_discharged',
            'delivered', 'empty_returned', name='milestonecode'), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_tasks_organization'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], name='fk_tasks_shipment'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tasks_organization_id', 'tasks', ['organization_id'])
    op.create_index('ix_tasks_shipment_id', 'tasks', ['shipment_id'])
    op.create_index('ix_tasks_due_at', 'tasks', ['due_at'])
    op.create_index('ix_tasks_code', 'tasks', ['code'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])
    op.create_index('ix_tasks_assignee_user_id', 'tasks', ['assignee_user_id'])
    op.create_index('ix_tasks_org_shipment', 'tasks', ['organization_id', 'shipment_id'])
    op.create_index('ix_tasks_org_status', 'tasks', ['organization_id', 'status'])

    # === operational_exceptions ===
    op.create_table(
        'operational_exceptions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('shipment_id', sa.String(length=36), nullable=False),
        sa.Column(
            'code',
            sa.Enum(
                'booking_response_overdue', 'booking_rejected', 'so_mismatch',
                'schedule_changed', 'port_changed', 'carrier_changed',
                'container_rolled', 'cutoff_approaching', 'cutoff_passed',
                'si_overdue', 'vgm_overdue', 'missing_container_no', 'missing_seal_no',
                'email_send_failed', 'email_parse_failed',
                name='exceptioncode',
            ),
            nullable=False,
        ),
        sa.Column(
            'severity',
            sa.Enum('info', 'warning', 'critical', name='exceptionseverity'),
            nullable=False, server_default='warning',
        ),
        sa.Column(
            'status',
            sa.Enum('open', 'resolved', 'auto_closed', name='exceptionstatus'),
            nullable=False, server_default='open',
        ),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'detected_by',
            sa.Enum('system', 'manual', name='exceptiondetectedby'),
            nullable=False, server_default='system',
        ),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.String(length=36), nullable=True),
        sa.Column('resolved_by_name', sa.String(length=128), nullable=True),
        sa.Column('resolution', sa.Text(), nullable=True),
        sa.Column('related_milestone_id', sa.String(length=36), nullable=True),
        sa.Column('related_task_id', sa.String(length=36), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_opex_organization'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], name='fk_opex_shipment'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_operational_exceptions_organization_id', 'operational_exceptions', ['organization_id'])
    op.create_index('ix_operational_exceptions_shipment_id', 'operational_exceptions', ['shipment_id'])
    op.create_index('ix_operational_exceptions_code', 'operational_exceptions', ['code'])
    op.create_index('ix_operational_exceptions_severity', 'operational_exceptions', ['severity'])
    op.create_index('ix_operational_exceptions_status', 'operational_exceptions', ['status'])
    op.create_index('ix_opex_org_shipment', 'operational_exceptions', ['organization_id', 'shipment_id'])
    op.create_index('ix_opex_org_status', 'operational_exceptions', ['organization_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_opex_org_status', table_name='operational_exceptions')
    op.drop_index('ix_opex_org_shipment', table_name='operational_exceptions')
    op.drop_index('ix_operational_exceptions_status', table_name='operational_exceptions')
    op.drop_index('ix_operational_exceptions_severity', table_name='operational_exceptions')
    op.drop_index('ix_operational_exceptions_code', table_name='operational_exceptions')
    op.drop_index('ix_operational_exceptions_shipment_id', table_name='operational_exceptions')
    op.drop_index('ix_operational_exceptions_organization_id', table_name='operational_exceptions')
    op.drop_table('operational_exceptions')
    op.execute("DROP TYPE IF EXISTS exceptiondetectedby")
    op.execute("DROP TYPE IF EXISTS exceptionstatus")
    op.execute("DROP TYPE IF EXISTS exceptionseverity")
    op.execute("DROP TYPE IF EXISTS exceptioncode")

    op.drop_index('ix_tasks_org_status', table_name='tasks')
    op.drop_index('ix_tasks_org_shipment', table_name='tasks')
    op.drop_index('ix_tasks_assignee_user_id', table_name='tasks')
    op.drop_index('ix_tasks_status', table_name='tasks')
    op.drop_index('ix_tasks_code', table_name='tasks')
    op.drop_index('ix_tasks_due_at', table_name='tasks')
    op.drop_index('ix_tasks_shipment_id', table_name='tasks')
    op.drop_index('ix_tasks_organization_id', table_name='tasks')
    op.drop_table('tasks')
    op.execute("DROP TYPE IF EXISTS taskstatus")
    op.execute("DROP TYPE IF EXISTS taskcode")

    op.drop_index('ix_milestones_shipment_occurred', table_name='milestones')
    op.drop_index('ix_milestones_org_shipment', table_name='milestones')
    op.drop_index('ix_milestones_code', table_name='milestones')
    op.drop_index('ix_milestones_shipment_id', table_name='milestones')
    op.drop_index('ix_milestones_organization_id', table_name='milestones')
    op.drop_table('milestones')
    op.execute("DROP TYPE IF EXISTS milestonesource")
    op.execute("DROP TYPE IF EXISTS milestonecode")
