"""add ovirt value to hypervisortype enum

Revision ID: f1a2b3c4d5e6
Revises: a9d8d838996f
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'a9d8d838996f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PROXMOX already exists in hypervisortype — only OVIRT is new.
    op.execute("ALTER TYPE hypervisortype ADD VALUE IF NOT EXISTS 'OVIRT'")


def downgrade() -> None:
    # PostgreSQL does not support removing a value from an enum without
    # recreating it, which is unsafe once rows reference the value.
    pass
