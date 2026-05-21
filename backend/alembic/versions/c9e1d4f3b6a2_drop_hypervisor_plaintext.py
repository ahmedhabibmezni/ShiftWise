"""drop hypervisor plaintext password column (cutover migration)

US4 — production-readiness bundle, cutover step (T048).

CAUTION: this revision is destructive. After it runs, the legacy
``hypervisors.password`` column is gone and the only way to recover a
credential is to decrypt ``password_ciphertext`` with the Fernet key.

OPERATOR PROCEDURE:
1. Apply revision ``b8d0c3e2a5f1`` (adds ciphertext + backfill).
2. Deploy the application code that reads via ``password_plain``.
3. Validate that every hypervisor connector still authenticates
   (see backend/tests/test_hypervisor_credential_storage.py for the
   property the connectors rely on).
4. Take a fresh database snapshot.
5. ONLY THEN apply this revision.

Until step 5 is taken, the legacy column is left in place so a fast
rollback during cutover does not lose data.

Revision ID: c9e1d4f3b6a2
Revises: b8d0c3e2a5f1
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e1d4f3b6a2"
down_revision: Union[str, None] = "b8d0c3e2a5f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("hypervisors", "password")


def downgrade() -> None:
    # Re-create the column as nullable; the plaintext content is gone for
    # good. The application's ``Hypervisor.password_plain`` falls back to
    # ``password`` only when ``password_ciphertext`` is NULL, so an empty
    # column is harmless for already-encrypted rows.
    op.add_column(
        "hypervisors",
        sa.Column("password", sa.Text(), nullable=True),
    )
