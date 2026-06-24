"""add last_login_at + last_login_ip to users

Adds two nullable audit columns to the `users` table:
- `last_login_at`  (TIMESTAMPTZ): horodatage UTC du dernier login réussi.
- `last_login_ip`  (VARCHAR(45)): IP de la connexion (depuis
  request.client.host).

Both are populated by /auth/login on every successful authentication.
Nullable so the upgrade is a non-blocking ALTER TABLE on a populated
database — existing rows simply stay NULL until each user's next login.

Revision ID: 7e9c0f2a8d11
Revises: 183dcd7f2613
Create Date: 2026-05-11 17:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '7e9c0f2a8d11'
down_revision: Union[str, None] = '183dcd7f2613'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Horodatage UTC de la dernière authentification réussie",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "last_login_ip",
            sa.String(length=45),
            nullable=True,
            comment="Adresse IP du dernier login (depuis request.client.host)",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_ip")
    op.drop_column("users", "last_login_at")
