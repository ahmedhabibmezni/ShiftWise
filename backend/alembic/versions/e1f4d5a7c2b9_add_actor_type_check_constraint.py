"""add CHECK constraint on migration_events.actor_type

Defense-in-depth follow-up to a7c9b2e1f4d8 (evolve migration_events).
The previous migration introduced ``actor_type`` as a free-form
``VARCHAR(16)`` and left validation to ``crud_migration_event.record_event``
(``_ALLOWED_ACTOR_TYPES``). A future raw-SQL job (archival routine,
ops script) could bypass the ORM and write a non-canonical string into
the audit log — a CHECK constraint at the DB layer closes that hole.

The constraint targets the three canonical values from Q1
(production-readiness): ``worker``, ``user``, ``system``.

Revision ID: e1f4d5a7c2b9
Revises: c9e1d4f3b6a2
Create Date: 2026-05-22

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e1f4d5a7c2b9"
down_revision: Union[str, None] = "c9e1d4f3b6a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONSTRAINT_NAME = "ck_migration_events_actor_type"
_CONSTRAINT_SQL = "actor_type IN ('worker', 'user', 'system')"


def upgrade() -> None:
    # Idempotent on PostgreSQL (handles re-running on a partially
    # migrated environment). SQLite uses ``create_check_constraint``
    # via batch alter mode in modern Alembic, but no in-repo SQLite
    # deployment runs this file — tests use ``create_all``.
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "migration_events",
        _CONSTRAINT_SQL,
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "migration_events",
        type_="check",
    )
