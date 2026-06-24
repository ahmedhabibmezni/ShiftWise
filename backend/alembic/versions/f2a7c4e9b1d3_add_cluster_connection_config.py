"""add cluster_connection_config and cluster_config_events

Feature 002 — Cluster Connectivity Management. Two tables:

- ``cluster_connection_config`` : une ligne par scope (défaut plateforme ou
  tenant). Secrets (kubeconfig / token) chiffrés au repos en ``LargeBinary``.
  Contraintes : unicité (scope_type, tenant_id) ; cohérence scope/tenant ;
  in-cluster réservé au défaut plateforme.
- ``cluster_config_events`` : journal append-only des changements. Un trigger
  PL/pgSQL bloque UPDATE/DELETE (PostgreSQL uniquement ; les tests SQLite
  utilisent create_all et s'appuient sur la couche applicative).

Les libellés d'enum sont les NOMS de membres (majuscules) — c'est ce que
SQLAlchemy ``SQLEnum`` lie (cf. règle CLAUDE.md).

Revision ID: f2a7c4e9b1d3
Revises: e1f4d5a7c2b9
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a7c4e9b1d3"
down_revision: Union[str, None] = "e1f4d5a7c2b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCOPE_ENUM = sa.Enum("PLATFORM_DEFAULT", "TENANT", name="clusterscopetype")
_MODE_ENUM = sa.Enum("KUBECONFIG", "INCLUSTER", "CUSTOM", name="clustermode")
_HEALTH_ENUM = sa.Enum(
    "HEALTHY", "DEGRADED", "UNREACHABLE", "AUTH_FAILED", "INVALID", "UNKNOWN",
    name="clusterhealthstatus",
)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.create_table(
        "cluster_connection_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope_type", _SCOPE_ENUM, nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=True),
        sa.Column("mode", _MODE_ENUM, nullable=False),
        sa.Column("kubeconfig_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("api_url", sa.String(length=512), nullable=True),
        sa.Column("token_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("verify_ssl", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "default_namespace", sa.String(length=253),
            nullable=False, server_default="default",
        ),
        sa.Column(
            "credential_key_version", sa.Integer(),
            nullable=False, server_default="1",
        ),
        sa.Column("credentials_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "health_status", _HEALTH_ENUM,
            nullable=False, server_default="UNKNOWN",
        ),
        sa.Column("health_reason", sa.String(length=512), nullable=True),
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.UniqueConstraint("scope_type", "tenant_id", name="uq_cluster_config_scope"),
        sa.CheckConstraint(
            "(scope_type = 'PLATFORM_DEFAULT' AND tenant_id IS NULL) "
            "OR (scope_type = 'TENANT' AND tenant_id IS NOT NULL)",
            name="ck_cluster_config_scope_tenant",
        ),
        sa.CheckConstraint(
            "mode <> 'INCLUSTER' OR scope_type = 'PLATFORM_DEFAULT'",
            name="ck_cluster_config_incluster_platform_only",
        ),
    )
    op.create_index(
        "ix_cluster_connection_config_scope_type",
        "cluster_connection_config", ["scope_type"],
    )
    op.create_index(
        "ix_cluster_connection_config_tenant_id",
        "cluster_connection_config", ["tenant_id"],
    )

    op.create_table(
        "cluster_config_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("config_scope_type", sa.String(length=20), nullable=False),
        sa.Column("config_tenant_id", sa.String(length=100), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("target_mode", sa.String(length=20), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system')",
            name="ck_cluster_config_events_actor_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('applied', 'rejected', 'failed')",
            name="ck_cluster_config_events_outcome",
        ),
    )

    # Append-only trigger (PostgreSQL uniquement).
    if is_postgres:
        op.execute(
            """
            CREATE OR REPLACE FUNCTION cluster_config_events_no_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'cluster_config_events is append-only';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_cluster_config_events_no_mutation "
            "ON cluster_config_events;"
        )
        op.execute(
            """
            CREATE TRIGGER trg_cluster_config_events_no_mutation
            BEFORE UPDATE OR DELETE ON cluster_config_events
            FOR EACH ROW
            EXECUTE FUNCTION cluster_config_events_no_mutation();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            "DROP TRIGGER IF EXISTS trg_cluster_config_events_no_mutation "
            "ON cluster_config_events;"
        )
        op.execute("DROP FUNCTION IF EXISTS cluster_config_events_no_mutation();")

    op.drop_table("cluster_config_events")
    op.drop_index(
        "ix_cluster_connection_config_tenant_id",
        table_name="cluster_connection_config",
    )
    op.drop_index(
        "ix_cluster_connection_config_scope_type",
        table_name="cluster_connection_config",
    )
    op.drop_table("cluster_connection_config")

    if is_postgres:
        _HEALTH_ENUM.drop(bind, checkfirst=True)
        _MODE_ENUM.drop(bind, checkfirst=True)
        _SCOPE_ENUM.drop(bind, checkfirst=True)
