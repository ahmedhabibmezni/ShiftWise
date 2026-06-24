"""add migration_events.row_hash for tamper-evident hash chaining

SV-021 — defense-in-depth complementary to SV-001. Adds a nullable
``row_hash`` column carrying ``sha256(prev_row_hash || canonical_payload)``
per ``migration_id`` (computed in ``crud.migration_event.record_event``). Any
deletion or edit of an audit row — including by a superuser bypassing the
append-only trigger — breaks the next row's hash and is detectable via
``crud.migration_event.verify_event_chain``.

Additive and nullable: existing rows keep ``row_hash = NULL`` (treated as
"legacy unchained" by the verifier). No backfill is performed — backfilling
would require UPDATEs that the append-only trigger blocks; new rows chain
forward from the next insert. ``ADD COLUMN`` is DDL and does not fire the
row-level trigger.

PostgreSQL-targeted; SQLite test fixtures use ``create_all`` and pick the
column up from the model directly.

Revision ID: b2d4f6a8c0e1
Revises: f9b3c1a7d2e4
Create Date: 2026-06-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2d4f6a8c0e1"
down_revision: Union[str, None] = "f9b3c1a7d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "migration_events",
        sa.Column("row_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("migration_events", "row_hash")
