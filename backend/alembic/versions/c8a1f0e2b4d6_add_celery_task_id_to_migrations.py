"""add celery_task_id to migrations

Adds a nullable `celery_task_id` (VARCHAR(64)) to the `migrations` table.
POST /migrations/{id}/start stores the run_migration Celery task id here so
POST /migrations/{id}/cancel can revoke the running task — without it,
cancelling only flips the status while the worker keeps running.

Nullable so the upgrade is a non-blocking ALTER TABLE on a populated
database — existing rows stay NULL (a task started before this column
cannot be revoked).

Revision ID: c8a1f0e2b4d6
Revises: 7e9c0f2a8d11
Create Date: 2026-05-17 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c8a1f0e2b4d6'
down_revision: Union[str, None] = '7e9c0f2a8d11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "migrations",
        sa.Column(
            "celery_task_id",
            sa.String(length=64),
            nullable=True,
            comment="Id de la tâche Celery run_migration, pour révocation à l'annulation",
        ),
    )


def downgrade() -> None:
    op.drop_column("migrations", "celery_task_id")
