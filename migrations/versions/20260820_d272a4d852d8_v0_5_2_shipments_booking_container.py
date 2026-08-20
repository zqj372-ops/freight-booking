"""v0_5_2_shipments_booking_container

Revision ID: d272a4d852d8
Revises: 458e1fbfafb4
Create Date: 2026-08-20 10:59:51.183488

v0.5 阶段 1.2: 业务聚合核心表
- shipments (聚合根)
- booking_requests (我发出)
- booking_confirmations (对方确认)
- containers (柜)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd272a4d852d8'
down_revision: Union[str, None] = '458e1fbfafb4'
branch_labels: Union[str, Sequence[str, None], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === shipments ===
    op.create_table(
        'shipments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('job_no', sa.String(length=64), nullable=False),
        sa.Column('legacy_job_no', sa.String(length=64), nullable=True),
        sa.Column('customer_ref', sa.String(length=128), nullable=True),
        sa.Column('carrier_booking_no', sa.String(length=64), nullable=True),
        sa.Column('so_no', sa.String(length=64), nullable=True),
        sa.Column('bl_no', sa.String(length=64), nullable=True),
        sa.Column(
            'stage',
            sa.Enum(
                'draft', 'booking_in_progress', 'awaiting_confirmation',
                'booked', 'container_operation', 'documentation',
                'departed', 'completed', 'cancelled',
                name='shipmentstage',
            ),
            nullable=False, server_default='draft',
        ),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('customer_partner_id', sa.String(length=36), nullable=True),
        sa.Column('pol', sa.String(length=64), nullable=False),
        sa.Column('pod', sa.String(length=64), nullable=False),
        sa.Column('final_destination', sa.String(length=64), nullable=True),
        sa.Column('target_etd', sa.Date(), nullable=False),
        sa.Column('etd', sa.Date(), nullable=True),
        sa.Column('eta', sa.Date(), nullable=True),
        sa.Column('commodity', sa.Text(), nullable=False),
        sa.Column('hs_code', sa.String(length=32), nullable=True),
        sa.Column('pieces', sa.Integer(), nullable=True),
        sa.Column('weight_kg', sa.Float(), nullable=True),
        sa.Column('volume_cbm', sa.Float(), nullable=True),
        sa.Column('is_dangerous', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_oversize', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('container_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('current_partner_id', sa.String(length=36), nullable=True),
        sa.Column('current_carrier', sa.String(length=64), nullable=True),
        sa.Column('operator_user_id', sa.String(length=36), nullable=True),
        sa.Column('operator_user_name', sa.String(length=128), nullable=True),
        sa.Column('sales_user_id', sa.String(length=36), nullable=True),
        sa.Column('sales_user_name', sa.String(length=128), nullable=True),
        sa.Column('rate_reference', sa.String(length=128), nullable=True),
        sa.Column('rate_valid_until', sa.Date(), nullable=True),
        sa.Column('commercial_snapshot', sa.JSON(), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_shipments_organization'),
        sa.ForeignKeyConstraint(['customer_partner_id'], ['partners.id'], name='fk_shipments_customer_partner', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['current_partner_id'], ['partners.id'], name='fk_shipments_current_partner', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'job_no', name='uq_shipments_org_job_no'),
        sa.UniqueConstraint('organization_id', 'legacy_job_no', name='uq_shipments_org_legacy_job_no'),
    )
    op.create_index('ix_shipments_organization_id', 'shipments', ['organization_id'])
    op.create_index('ix_shipments_job_no', 'shipments', ['job_no'])
    op.create_index('ix_shipments_legacy_job_no', 'shipments', ['legacy_job_no'])
    op.create_index('ix_shipments_customer_ref', 'shipments', ['customer_ref'])
    op.create_index('ix_shipments_carrier_booking_no', 'shipments', ['carrier_booking_no'])
    op.create_index('ix_shipments_stage', 'shipments', ['stage'])
    op.create_index('ix_shipments_pol', 'shipments', ['pol'])
    op.create_index('ix_shipments_pod', 'shipments', ['pod'])
    op.create_index('ix_shipments_customer_partner_id', 'shipments', ['customer_partner_id'])
    op.create_index('ix_shipments_current_partner_id', 'shipments', ['current_partner_id'])
    op.create_index('ix_shipments_current_carrier', 'shipments', ['current_carrier'])
    op.create_index('ix_shipments_operator_user_id', 'shipments', ['operator_user_id'])
    op.create_index('ix_shipments_org_stage', 'shipments', ['organization_id', 'stage'])
    op.create_index('ix_shipments_org_target_etd', 'shipments', ['organization_id', 'target_etd'])

    # === booking_requests ===
    op.create_table(
        'booking_requests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('shipment_id', sa.String(length=36), nullable=False),
        sa.Column('partner_id', sa.String(length=36), nullable=False),
        sa.Column('booking_request_no', sa.String(length=32), nullable=False),
        sa.Column('request_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('supersedes_id', sa.String(length=36), nullable=True),
        sa.Column('cargo_snapshot', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('requested_etd', sa.Date(), nullable=False),
        sa.Column('requested_pol', sa.String(length=64), nullable=False),
        sa.Column('requested_pod', sa.String(length=64), nullable=False),
        sa.Column('requested_container_type', sa.String(length=16), nullable=False, server_default='40HQ'),
        sa.Column('requested_container_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('carrier_preference', sa.String(length=64), nullable=True),
        sa.Column('email_thread_id', sa.String(length=36), nullable=True),
        sa.Column('email_message_id', sa.String(length=36), nullable=True),
        sa.Column('email_account_id', sa.String(length=36), nullable=True),
        sa.Column(
            'status',
            sa.Enum(
                'draft', 'sent', 'acknowledged', 'confirmed', 'rejected', 'cancelled',
                name='bookingrequeststatus',
            ),
            nullable=False, server_default='draft',
        ),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('expected_response_by', sa.DateTime(timezone=True), nullable=True),
        sa.Column('response_sla_hours', sa.Integer(), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_booking_requests_organization'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], name='fk_booking_requests_shipment', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], name='fk_booking_requests_partner'),
        sa.ForeignKeyConstraint(['supersedes_id'], ['booking_requests.id'], name='fk_booking_requests_supersedes', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shipment_id', 'booking_request_no', name='uq_booking_requests_shipment_no'),
    )
    op.create_index('ix_booking_requests_organization_id', 'booking_requests', ['organization_id'])
    op.create_index('ix_booking_requests_shipment_id', 'booking_requests', ['shipment_id'])
    op.create_index('ix_booking_requests_partner_id', 'booking_requests', ['partner_id'])
    op.create_index('ix_booking_requests_status', 'booking_requests', ['status'])
    op.create_index('ix_booking_requests_org_status', 'booking_requests', ['organization_id', 'status'])

    # === booking_confirmations ===
    op.create_table(
        'booking_confirmations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('shipment_id', sa.String(length=36), nullable=False),
        sa.Column('booking_request_id', sa.String(length=36), nullable=True),
        sa.Column('document_id', sa.String(length=36), nullable=True),
        sa.Column('extraction_id', sa.String(length=36), nullable=True),
        sa.Column('carrier', sa.String(length=64), nullable=True),
        sa.Column('carrier_booking_no', sa.String(length=64), nullable=True),
        sa.Column('so_no', sa.String(length=64), nullable=True),
        sa.Column('bl_no', sa.String(length=64), nullable=True),
        sa.Column('vessel_name', sa.String(length=128), nullable=True),
        sa.Column('voyage_no', sa.String(length=32), nullable=True),
        sa.Column('pol', sa.String(length=64), nullable=True),
        sa.Column('pod', sa.String(length=64), nullable=True),
        sa.Column('etd', sa.Date(), nullable=True),
        sa.Column('eta', sa.Date(), nullable=True),
        sa.Column('cy_open_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('si_cutoff_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('vgm_cutoff_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cy_cutoff_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('container_type', sa.String(length=16), nullable=True),
        sa.Column('container_count', sa.Integer(), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('supersedes_id', sa.String(length=36), nullable=True),
        sa.Column(
            'status',
            sa.Enum(
                'unmatched', 'matched_pending', 'accepted', 'superseded', 'rejected', 'duplicate',
                name='bookingconfirmationstatus',
            ),
            nullable=False, server_default='unmatched',
        ),
        sa.Column(
            'review_status',
            sa.Enum('needs_review', 'reviewed', name='bookingconfirmationreviewstatus'),
            nullable=False, server_default='needs_review',
        ),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accepted_by', sa.String(length=36), nullable=True),
        sa.Column('accepted_by_name', sa.String(length=128), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_booking_confirmations_organization'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], name='fk_booking_confirmations_shipment', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['booking_request_id'], ['booking_requests.id'], name='fk_booking_confirmations_booking_request', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shipment_id', 'version', name='uq_booking_confirmations_shipment_version'),
    )
    op.create_index('ix_booking_confirmations_organization_id', 'booking_confirmations', ['organization_id'])
    op.create_index('ix_booking_confirmations_shipment_id', 'booking_confirmations', ['shipment_id'])
    op.create_index('ix_booking_confirmations_booking_request_id', 'booking_confirmations', ['booking_request_id'])
    op.create_index('ix_booking_confirmations_document_id', 'booking_confirmations', ['document_id'])
    op.create_index('ix_booking_confirmations_carrier', 'booking_confirmations', ['carrier'])
    op.create_index('ix_booking_confirmations_carrier_booking_no', 'booking_confirmations', ['carrier_booking_no'])
    op.create_index('ix_booking_confirmations_so_no', 'booking_confirmations', ['so_no'])
    op.create_index('ix_booking_confirmations_status', 'booking_confirmations', ['status'])
    op.create_index('ix_booking_confirmations_is_current', 'booking_confirmations', ['is_current'])
    op.create_index('ix_booking_confirmations_org_status', 'booking_confirmations', ['organization_id', 'status'])
    op.create_index('ix_booking_confirmations_shipment_current', 'booking_confirmations', ['shipment_id', 'is_current'])

    # === containers ===
    op.create_table(
        'containers',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('shipment_id', sa.String(length=36), nullable=False),
        sa.Column('container_no', sa.String(length=32), nullable=True),
        sa.Column('seal_no', sa.String(length=32), nullable=True),
        sa.Column('container_type', sa.String(length=16), nullable=False, server_default='40HQ'),
        sa.Column('pickup_location', sa.String(length=255), nullable=True),
        sa.Column('pickup_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('loaded_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('return_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pieces', sa.Integer(), nullable=True),
        sa.Column('gross_weight_kg', sa.Float(), nullable=True),
        sa.Column('volume_cbm', sa.Float(), nullable=True),
        sa.Column(
            'status',
            sa.Enum(
                'pending', 'picked_up', 'loaded', 'in_transit', 'discharged', 'returned',
                name='containerstatus',
            ),
            nullable=False, server_default='pending',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_containers_organization'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], name='fk_containers_shipment', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_containers_organization_id', 'containers', ['organization_id'])
    op.create_index('ix_containers_shipment_id', 'containers', ['shipment_id'])
    op.create_index('ix_containers_container_no', 'containers', ['container_no'])
    op.create_index('ix_containers_status', 'containers', ['status'])
    op.create_index('ix_containers_org_status', 'containers', ['organization_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_containers_org_status', table_name='containers')
    op.drop_index('ix_containers_status', table_name='containers')
    op.drop_index('ix_containers_container_no', table_name='containers')
    op.drop_index('ix_containers_shipment_id', table_name='containers')
    op.drop_index('ix_containers_organization_id', table_name='containers')
    op.drop_table('containers')
    op.execute("DROP TYPE IF EXISTS containerstatus")

    op.drop_index('ix_booking_confirmations_shipment_current', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_org_status', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_is_current', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_status', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_so_no', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_carrier_booking_no', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_carrier', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_document_id', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_booking_request_id', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_shipment_id', table_name='booking_confirmations')
    op.drop_index('ix_booking_confirmations_organization_id', table_name='booking_confirmations')
    op.drop_table('booking_confirmations')
    op.execute("DROP TYPE IF EXISTS bookingconfirmationreviewstatus")
    op.execute("DROP TYPE IF EXISTS bookingconfirmationstatus")

    op.drop_index('ix_booking_requests_org_status', table_name='booking_requests')
    op.drop_index('ix_booking_requests_status', table_name='booking_requests')
    op.drop_index('ix_booking_requests_partner_id', table_name='booking_requests')
    op.drop_index('ix_booking_requests_shipment_id', table_name='booking_requests')
    op.drop_index('ix_booking_requests_organization_id', table_name='booking_requests')
    op.drop_table('booking_requests')
    op.execute("DROP TYPE IF EXISTS bookingrequeststatus")

    op.drop_index('ix_shipments_org_target_etd', table_name='shipments')
    op.drop_index('ix_shipments_org_stage', table_name='shipments')
    op.drop_index('ix_shipments_operator_user_id', table_name='shipments')
    op.drop_index('ix_shipments_current_carrier', table_name='shipments')
    op.drop_index('ix_shipments_current_partner_id', table_name='shipments')
    op.drop_index('ix_shipments_customer_partner_id', table_name='shipments')
    op.drop_index('ix_shipments_pod', table_name='shipments')
    op.drop_index('ix_shipments_pol', table_name='shipments')
    op.drop_index('ix_shipments_stage', table_name='shipments')
    op.drop_index('ix_shipments_carrier_booking_no', table_name='shipments')
    op.drop_index('ix_shipments_customer_ref', table_name='shipments')
    op.drop_index('ix_shipments_legacy_job_no', table_name='shipments')
    op.drop_index('ix_shipments_job_no', table_name='shipments')
    op.drop_index('ix_shipments_organization_id', table_name='shipments')
    op.drop_table('shipments')
    op.execute("DROP TYPE IF EXISTS shipmentstage")
