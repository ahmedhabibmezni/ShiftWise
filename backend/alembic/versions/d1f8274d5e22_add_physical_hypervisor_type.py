"""add physical hypervisor type

Revision ID: d1f8274d5e22
Revises: b2d4f6a8c0e1
Create Date: 2026-06-15 01:54:34.053480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1f8274d5e22'
down_revision: Union[str, None] = 'b2d4f6a8c0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE hypervisortype ADD VALUE IF NOT EXISTS 'PHYSICAL'")


def downgrade() -> None:
    # PostgreSQL cannot DROP a VALUE from an enum type without recreating it.
    # Removing an enum label is intentionally a no-op (matches the project's
    # other enum-add migrations, e.g. d2f1a0c3e8b7).
    pass
