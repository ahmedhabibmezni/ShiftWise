"""add hypervisor credential ciphertext columns and backfill from plaintext

US4 — production-readiness bundle (data-model § 2). Adds:
- ``password_ciphertext`` (LargeBinary) — Fernet-encrypted credential.
- ``credential_key_version`` (Integer, default 1) — which key encrypted
  the row, useful when rotation happens.
- ``credentials_updated_at`` (timezone-aware datetime) — last
  encryption timestamp.

Backfill: for every row with a non-NULL ``password``, encrypt the value
via :func:`get_vault` and store it in ``password_ciphertext``; then NULL
out the legacy ``password`` column so subsequent reads via
``Hypervisor.password_plain`` come from the ciphertext path.

The legacy ``password`` column itself is also made nullable in this
migration — the cutover that DROPs it lives in a separate Alembic
revision (c9e1d4f3b6a2) so a fast rollback during this deploy does not
destroy encrypted data.

The migration is idempotent: re-running over an already-encrypted row
detects ``password_ciphertext IS NOT NULL`` and skips it.

Revision ID: b8d0c3e2a5f1
Revises: a7c9b2e1f4d8
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d0c3e2a5f1"
down_revision: Union[str, None] = "a7c9b2e1f4d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add the three new columns. ``credential_key_version`` defaults
    #    to 1 so existing rows match the initial vault key version.
    op.add_column(
        "hypervisors",
        sa.Column("password_ciphertext", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "hypervisors",
        sa.Column(
            "credential_key_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "hypervisors",
        sa.Column(
            "credentials_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )

    # 2. Relax the legacy plaintext column so the cutover (which drops it)
    #    can land later without forcing a NOT NULL backfill on rows that
    #    already moved to ciphertext.
    op.alter_column("hypervisors", "password", nullable=True)

    # 3. Backfill — encrypt every existing plaintext password into
    #    password_ciphertext, then NULL the legacy column. We import the
    #    application vault here rather than embedding Fernet keys into a
    #    migration file (the key MUST live in the OpenShift Secret).
    bind = op.get_bind()
    hypervisors = sa.table(
        "hypervisors",
        sa.column("id", sa.Integer()),
        sa.column("password", sa.Text()),
        sa.column("password_ciphertext", sa.LargeBinary()),
    )

    rows = bind.execute(
        sa.select(hypervisors.c.id, hypervisors.c.password)
        .where(hypervisors.c.password_ciphertext.is_(None))
        .where(hypervisors.c.password.isnot(None))
    ).fetchall()

    if rows:
        # Defer the vault import — the migration must still run in CI /
        # tests where the Fernet key env var may be absent. In that case
        # the application vault raises and the migration aborts loudly,
        # which is the right behavior: encrypting against a missing key
        # would be worse than failing.
        from app.services.credentials import get_vault

        vault = get_vault()
        for row in rows:
            ciphertext = vault.encrypt(row.password)
            bind.execute(
                hypervisors.update()
                .where(hypervisors.c.id == row.id)
                .values(password_ciphertext=ciphertext, password=None)
            )


def downgrade() -> None:
    # Reverse, in roughly the inverse order. We cannot recover the
    # plaintext from ciphertext without the Fernet key — but the
    # ``password`` column was made nullable, so dropping the ciphertext
    # leaves rows with the legacy plaintext still present (NULL for any
    # row that the upgrade backfilled). Operators rolling back MUST
    # ensure plaintext credentials still exist out-of-band; otherwise
    # the connectors will fail authenticating after rollback.

    op.drop_column("hypervisors", "credentials_updated_at")
    op.drop_column("hypervisors", "credential_key_version")
    op.drop_column("hypervisors", "password_ciphertext")
    # Re-tighten the legacy column. If any row has a NULL password at
    # this point, the alter will fail — the operator must repopulate
    # plaintext manually before rolling back further.
    op.alter_column("hypervisors", "password", nullable=False)
