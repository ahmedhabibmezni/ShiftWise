"""add discovering status to hypervisor enum

Revision ID: 53e5a25cf4d0
Revises: a3a25e5c165d
Create Date: 2026-03-12 06:17:06.004709

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53e5a25cf4d0'
down_revision: Union[str, None] = 'a3a25e5c165d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter la nouvelle valeur 'discovering' à l'enum hypervisorstatus
    op.execute("ALTER TYPE hypervisorstatus ADD VALUE IF NOT EXISTS 'discovering'")


def downgrade() -> None:
    # PostgreSQL ne permet pas de supprimer facilement une valeur d'enum
    # Il faudrait recréer l'enum, ce qui est complexe en production
    pass