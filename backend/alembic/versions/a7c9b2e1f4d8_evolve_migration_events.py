"""evolve migration_events: sequence_id + actor + new event_type enum + append-only trigger

Production-readiness bundle (US3 / data model § 1, research § R4, R9, Q1, Q2,
Q3, FR-007). The previous migration (e3f5a8c1d2b4) introduced the table with
three event types (STATUS_CHANGE / ERROR / NOTE) and FK CASCADE; this
revision evolves it to the production shape:

- Adds ``sequence_id`` (monotonic per migration, primitive d'ordre canonique).
- Adds ``actor_id`` (FK users, ON DELETE SET NULL) and ``actor_type``.
- Renames the enum values to the four canonical types from Q1
  (state_transition / stage_event / classified_error / heartbeat) and casts
  existing rows (STATUS_CHANGE → state_transition, ERROR → classified_error,
  NOTE → stage_event).
- Replaces the ON DELETE CASCADE FK on ``migration_id`` with NO ACTION so
  the audit lifetime is independent of the parent migration (Q3.A, FR-007).
- Adds the ``(migration_id, sequence_id)`` unique constraint (Q2 identity).
- Adds the ``event_type`` cross-migration index (R9).
- Installs an append-only PL/pgSQL trigger blocking UPDATE/DELETE on
  ``migration_events`` (R4 defense-in-depth) — exempted only for the
  migration runner role identified by ``shiftwise.migration_role``.

The migration is PostgreSQL-targeted. SQLite (used by the in-memory test
fixtures) uses ``Base.metadata.create_all`` directly and never runs this
file, so dialect-specific blocks below are guarded for that case.

Revision ID: a7c9b2e1f4d8
Revises: e3f5a8c1d2b4
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c9b2e1f4d8"
down_revision: Union[str, None] = "e3f5a8c1d2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ENUM_NAME = "migrationeventtype"
_ENUM_OLD_NAME = "migrationeventtype_old"
_NEW_VALUES = (
    "state_transition",
    "stage_event",
    "classified_error",
    "heartbeat",
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    is_postgres = dialect == "postgresql"

    # 1. Add the three new columns (nullable for now, backfill below).
    op.add_column(
        "migration_events",
        sa.Column("sequence_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "migration_events",
        sa.Column("actor_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "migration_events",
        sa.Column(
            "actor_type",
            sa.String(length=16),
            nullable=False,
            server_default="worker",
        ),
    )

    # 2. Backfill sequence_id via ROW_NUMBER() PARTITION BY migration_id.
    if is_postgres:
        op.execute(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY migration_id
                           ORDER BY id ASC
                       ) AS rn
                FROM migration_events
            )
            UPDATE migration_events AS e
            SET sequence_id = ranked.rn
            FROM ranked
            WHERE e.id = ranked.id;
            """
        )
    else:
        # SQLite / generic SQL — emulate with a correlated subquery.
        op.execute(
            """
            UPDATE migration_events
            SET sequence_id = (
                SELECT COUNT(*)
                FROM migration_events AS e2
                WHERE e2.migration_id = migration_events.migration_id
                  AND e2.id <= migration_events.id
            );
            """
        )

    # 3. Make sequence_id non-nullable now that backfill is complete.
    op.alter_column("migration_events", "sequence_id", nullable=False)

    # 4. Add FK actor_id -> users.id (ON DELETE SET NULL).
    op.create_foreign_key(
        "fk_migration_events_actor",
        "migration_events",
        "users",
        ["actor_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 5. Replace FK on migration_id: CASCADE -> NO ACTION (Q3.A).
    #    The original migration did not name the FK, so we drop it via
    #    introspection in PostgreSQL.
    if is_postgres:
        op.execute(
            """
            DO $$
            DECLARE
                con_name text;
            BEGIN
                SELECT conname INTO con_name
                FROM pg_constraint
                WHERE conrelid = 'migration_events'::regclass
                  AND contype = 'f'
                  AND pg_get_constraintdef(oid)
                      LIKE '%(migration_id)%REFERENCES migrations%';
                IF con_name IS NOT NULL THEN
                    EXECUTE format(
                        'ALTER TABLE migration_events DROP CONSTRAINT %I',
                        con_name
                    );
                END IF;
            END$$;
            """
        )
        op.create_foreign_key(
            "fk_migration_events_migration_no_action",
            "migration_events",
            "migrations",
            ["migration_id"],
            ["id"],
            ondelete="NO ACTION",
        )

    # 6. Replace the enum values. PostgreSQL: rename old type, create new,
    #    cast each row. The cast is a one-shot mapping documented in the
    #    migration docstring.
    if is_postgres:
        op.execute(
            f"ALTER TYPE {_ENUM_NAME} RENAME TO {_ENUM_OLD_NAME};"
        )
        new_values_sql = ", ".join(f"'{v}'" for v in _NEW_VALUES)
        op.execute(f"CREATE TYPE {_ENUM_NAME} AS ENUM ({new_values_sql});")
        # Drop the server_default temporarily so the column cast can run.
        op.execute(
            "ALTER TABLE migration_events ALTER COLUMN event_type DROP DEFAULT;"
        )
        op.execute(
            f"""
            ALTER TABLE migration_events
            ALTER COLUMN event_type TYPE {_ENUM_NAME}
            USING (
                CASE event_type::text
                    WHEN 'STATUS_CHANGE' THEN 'state_transition'
                    WHEN 'ERROR'         THEN 'classified_error'
                    WHEN 'NOTE'          THEN 'stage_event'
                    ELSE event_type::text
                END
            )::{_ENUM_NAME};
            """
        )
        op.execute(
            f"ALTER TABLE migration_events ALTER COLUMN event_type "
            f"SET DEFAULT '{_NEW_VALUES[0]}';"
        )
        op.execute(f"DROP TYPE {_ENUM_OLD_NAME};")

    # 7. Add unique constraint and event_type index (R9).
    op.create_unique_constraint(
        "uq_migration_events_seq",
        "migration_events",
        ["migration_id", "sequence_id"],
    )
    op.create_index(
        "ix_migration_events_event_type",
        "migration_events",
        ["event_type"],
    )

    # 8. Install append-only trigger (PostgreSQL only — sqlite tests use
    #    create_all and rely on the application layer for append-only).
    if is_postgres:
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
        op.execute(
            "DROP TRIGGER IF EXISTS trg_migration_events_no_mutation "
            "ON migration_events;"
        )
        op.execute(
            """
            CREATE TRIGGER trg_migration_events_no_mutation
            BEFORE UPDATE OR DELETE ON migration_events
            FOR EACH ROW
            EXECUTE FUNCTION migration_events_no_mutation();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    is_postgres = dialect == "postgresql"

    # 8 reverse — drop the append-only trigger and function.
    if is_postgres:
        op.execute(
            "DROP TRIGGER IF EXISTS trg_migration_events_no_mutation "
            "ON migration_events;"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS migration_events_no_mutation();"
        )

    # 7 reverse — drop event_type index and unique constraint.
    op.drop_index(
        "ix_migration_events_event_type", table_name="migration_events"
    )
    op.drop_constraint(
        "uq_migration_events_seq", "migration_events", type_="unique"
    )

    # 6 reverse — restore the old enum and cast rows back.
    if is_postgres:
        op.execute(
            f"ALTER TYPE {_ENUM_NAME} RENAME TO {_ENUM_OLD_NAME};"
        )
        op.execute(
            f"CREATE TYPE {_ENUM_NAME} AS ENUM "
            "('STATUS_CHANGE', 'ERROR', 'NOTE');"
        )
        op.execute(
            "ALTER TABLE migration_events ALTER COLUMN event_type DROP DEFAULT;"
        )
        op.execute(
            f"""
            ALTER TABLE migration_events
            ALTER COLUMN event_type TYPE {_ENUM_NAME}
            USING (
                CASE event_type::text
                    WHEN 'state_transition'  THEN 'STATUS_CHANGE'
                    WHEN 'classified_error'  THEN 'ERROR'
                    WHEN 'stage_event'       THEN 'NOTE'
                    WHEN 'heartbeat'         THEN 'NOTE'
                    ELSE event_type::text
                END
            )::{_ENUM_NAME};
            """
        )
        op.execute(
            "ALTER TABLE migration_events ALTER COLUMN event_type "
            "SET DEFAULT 'STATUS_CHANGE';"
        )
        op.execute(f"DROP TYPE {_ENUM_OLD_NAME};")

    # 5 reverse — restore CASCADE FK on migration_id.
    if is_postgres:
        op.execute(
            "ALTER TABLE migration_events "
            "DROP CONSTRAINT IF EXISTS fk_migration_events_migration_no_action;"
        )
        op.create_foreign_key(
            None,
            "migration_events",
            "migrations",
            ["migration_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # 4 reverse — drop actor FK.
    op.drop_constraint(
        "fk_migration_events_actor",
        "migration_events",
        type_="foreignkey",
    )

    # 1-3 reverse — drop the three new columns.
    op.drop_column("migration_events", "actor_type")
    op.drop_column("migration_events", "actor_id")
    op.drop_column("migration_events", "sequence_id")
