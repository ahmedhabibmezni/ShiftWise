"""add migration_events audit table

Audit J1 — journal append-only des transitions de la machine à états d'une
migration. Permet un replay complet même après reprise d'un worker Celery
ou redémarrage de la base.

Revision ID: e3f5a8c1d2b4
Revises: d2f1a0c3e8b7
Create Date: 2026-05-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f5a8c1d2b4"
down_revision: Union[str, None] = "d2f1a0c3e8b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "migration_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("migration_id", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "STATUS_CHANGE",
                "ERROR",
                "NOTE",
                name="migrationeventtype",
            ),
            nullable=False,
            server_default="STATUS_CHANGE",
        ),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["migration_id"], ["migrations.id"], ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_migration_events_tenant_id",
        "migration_events",
        ["tenant_id"],
    )
    op.create_index(
        "ix_migration_events_migration_created",
        "migration_events",
        ["migration_id", "created_at"],
    )
    op.create_index(
        "ix_migration_events_tenant_created",
        "migration_events",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_migration_events_tenant_created", table_name="migration_events",
    )
    op.drop_index(
        "ix_migration_events_migration_created", table_name="migration_events",
    )
    op.drop_index(
        "ix_migration_events_tenant_id", table_name="migration_events",
    )
    op.drop_table("migration_events")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS migrationeventtype")
