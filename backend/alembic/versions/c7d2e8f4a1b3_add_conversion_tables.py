"""add conversion_groups, conversion_jobs, conversion_attempts tables

Revision ID: c7d2e8f4a1b3
Revises: f1a2b3c4d5e6
Create Date: 2026-04-26 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c7d2e8f4a1b3'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Column-side enum references (no CREATE TYPE — types are created
# explicitly via raw SQL below to avoid duplicate-create races between
# the Enum object and op.create_table).
GROUP_STATUS = postgresql.ENUM(name='conversiongroupstatus', create_type=False)
JOB_STATUS = postgresql.ENUM(name='conversionstatus', create_type=False)
SOURCE_FORMAT = postgresql.ENUM(name='sourceformat', create_type=False)
TARGET_FORMAT = postgresql.ENUM(name='targetformat', create_type=False)
TOOL = postgresql.ENUM(name='conversiontool', create_type=False)


def upgrade() -> None:
    # Create enum types explicitly (idempotent).
    op.execute("CREATE TYPE conversiongroupstatus AS ENUM ("
               "'PENDING','IN_PROGRESS','READY','PARTIAL','FAILED','CANCELLED')")
    op.execute("CREATE TYPE conversionstatus AS ENUM ("
               "'PENDING','PLANNING','STAGING','CONVERTING','VERIFYING',"
               "'READY','FAILED','CANCELLED','RETRYING','EXPIRED')")
    op.execute("CREATE TYPE sourceformat AS ENUM ("
               "'VMDK','VHD','VHDX','QCOW2','RAW')")
    op.execute("CREATE TYPE targetformat AS ENUM ('QCOW2','RAW')")
    op.execute("CREATE TYPE conversiontool AS ENUM ("
               "'QEMU_IMG','VIRT_V2V','PASSTHROUGH')")

    op.create_table(
        'conversion_groups',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('tenant_id', sa.String(100), nullable=False),
        sa.Column('vm_id', sa.Integer(), nullable=False),
        sa.Column('migration_id', sa.Integer(), nullable=True),
        sa.Column('group_uuid', sa.String(36), nullable=False),
        sa.Column('status', GROUP_STATUS, nullable=False, server_default='PENDING'),
        sa.Column('target_format', TARGET_FORMAT, nullable=False, server_default='QCOW2'),
        sa.Column('pull_config', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['vm_id'], ['virtual_machines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['migration_id'], ['migrations.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('group_uuid', name='uq_conversion_groups_uuid'),
    )
    op.create_index('ix_conversion_groups_tenant_id', 'conversion_groups', ['tenant_id'])
    op.create_index('ix_conversion_groups_vm_id', 'conversion_groups', ['vm_id'])
    op.create_index('ix_conversion_groups_migration_id', 'conversion_groups', ['migration_id'])
    op.create_index('ix_conversion_groups_status', 'conversion_groups', ['status'])
    op.create_index('ix_conversion_groups_group_uuid', 'conversion_groups', ['group_uuid'])

    op.create_table(
        'conversion_jobs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('tenant_id', sa.String(100), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('vm_id', sa.Integer(), nullable=False),
        sa.Column('disk_index', sa.Integer(), nullable=False),
        sa.Column('source_format', SOURCE_FORMAT, nullable=False),
        sa.Column('target_format', TARGET_FORMAT, nullable=False, server_default='QCOW2'),
        sa.Column('tool', TOOL, nullable=False),
        sa.Column('source_path', sa.String(512), nullable=True),
        sa.Column('staged_path', sa.String(512), nullable=True),
        sa.Column('output_path', sa.String(512), nullable=True),
        sa.Column('source_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('output_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('sha256', sa.String(64), nullable=True),
        sa.Column('status', JOB_STATUS, nullable=False, server_default='PENDING'),
        sa.Column('progress_pct', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('celery_task_id', sa.String(64), nullable=True),
        sa.Column('k8s_job_name', sa.String(253), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['group_id'], ['conversion_groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vm_id'], ['virtual_machines.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('group_id', 'disk_index', name='uq_conversion_jobs_group_disk'),
    )
    op.create_index('ix_conversion_jobs_tenant_id', 'conversion_jobs', ['tenant_id'])
    op.create_index('ix_conversion_jobs_group_id', 'conversion_jobs', ['group_id'])
    op.create_index('ix_conversion_jobs_vm_id', 'conversion_jobs', ['vm_id'])
    op.create_index('ix_conversion_jobs_status', 'conversion_jobs', ['status'])
    op.create_index('ix_conversion_jobs_error_code', 'conversion_jobs', ['error_code'])
    op.create_index('ix_conversion_jobs_celery_task_id', 'conversion_jobs', ['celery_task_id'])
    op.create_index('ix_conversion_jobs_status_tenant', 'conversion_jobs', ['status', 'tenant_id'])

    op.create_table(
        'conversion_attempts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('final_status', JOB_STATUS, nullable=False),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('log_path', sa.String(512), nullable=True),
        sa.Column('tool_exit_code', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['conversion_jobs.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('job_id', 'attempt_number', name='uq_conversion_attempts_job_attempt'),
    )
    op.create_index('ix_conversion_attempts_job_id', 'conversion_attempts', ['job_id'])


def downgrade() -> None:
    op.drop_index('ix_conversion_attempts_job_id', table_name='conversion_attempts')
    op.drop_table('conversion_attempts')

    op.drop_index('ix_conversion_jobs_status_tenant', table_name='conversion_jobs')
    op.drop_index('ix_conversion_jobs_celery_task_id', table_name='conversion_jobs')
    op.drop_index('ix_conversion_jobs_error_code', table_name='conversion_jobs')
    op.drop_index('ix_conversion_jobs_status', table_name='conversion_jobs')
    op.drop_index('ix_conversion_jobs_vm_id', table_name='conversion_jobs')
    op.drop_index('ix_conversion_jobs_group_id', table_name='conversion_jobs')
    op.drop_index('ix_conversion_jobs_tenant_id', table_name='conversion_jobs')
    op.drop_table('conversion_jobs')

    op.drop_index('ix_conversion_groups_group_uuid', table_name='conversion_groups')
    op.drop_index('ix_conversion_groups_status', table_name='conversion_groups')
    op.drop_index('ix_conversion_groups_migration_id', table_name='conversion_groups')
    op.drop_index('ix_conversion_groups_vm_id', table_name='conversion_groups')
    op.drop_index('ix_conversion_groups_tenant_id', table_name='conversion_groups')
    op.drop_table('conversion_groups')

    op.execute("DROP TYPE IF EXISTS conversiontool")
    op.execute("DROP TYPE IF EXISTS targetformat")
    op.execute("DROP TYPE IF EXISTS sourceformat")
    op.execute("DROP TYPE IF EXISTS conversionstatus")
    op.execute("DROP TYPE IF EXISTS conversiongroupstatus")
