"""harden migration_events append-only trigger: remove session-GUC escape hatch

SV-001 — the append-only trigger function ``migration_events_no_mutation()``
introduced in ``a7c9b2e1f4d8`` contained a self-defeating escape hatch:

    IF current_setting('shiftwise.migration_role', true) = 'migration_runner'
        THEN RETURN COALESCE(NEW, OLD);   -- mutation allowed

A user-defined GUC in a custom namespace (``shiftwise.*``) is settable by ANY
role via ``SET`` — no privilege, no GRANT, no role check. So the predicate was
not an authorization check at all: any caller could assert the magic value
about itself and then UPDATE/DELETE audit rows. This made the documented
"append-only at the storage layer" guarantee hollow.

This revision redefines the function to **unconditionally** raise on any
UPDATE/DELETE, matching the (non-vulnerable) ``cluster_config_events`` pattern.
No application code path relies on the GUC (verified: nothing sets
``shiftwise.migration_role``), so removing it changes no legitimate behaviour —
the API never hard-mutates audit rows (DELETE /migrations/{id} returns 409 when
events exist).

Note (out of scope here — deployment task): a superuser / table owner can still
bypass any trigger via DISABLE TRIGGER / TRUNCATE / DROP. The complete fix also
requires running the application as a non-owner, least-privilege DB role (the
app currently connects as ``postgres``). That is provisioned at deployment time.

PostgreSQL-targeted. SQLite test fixtures use ``create_all`` and never run this
file, so the body is guarded for the non-postgres dialect.

Revision ID: f9b3c1a7d2e4
Revises: f2a7c4e9b1d3
Create Date: 2026-06-12
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f9b3c1a7d2e4"
down_revision: Union[str, None] = "f2a7c4e9b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Redefine the function in place — the trigger keeps pointing at it, so no
    # trigger drop/recreate is needed. CREATE OR REPLACE swaps the body
    # atomically.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION migration_events_no_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'migration_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Restore the original (GUC-gated) body. This re-opens SV-001 and exists
    # only for migration symmetry; do not run it in a deployment you intend to
    # keep secure.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION migration_events_no_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF current_setting('shiftwise.migration_role', true)
                    = 'migration_runner' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION 'migration_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
