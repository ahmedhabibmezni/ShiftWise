"""fix DISCOVERING hypervisorstatus enum label case

Audit D2 / C-09 — revision 53e5a25cf4d0 added the value to the
``hypervisorstatus`` PostgreSQL enum as lowercase ``'discovering'``.
SQLAlchemy's ``Enum(HypervisorStatus)`` binds the enum member *name*
(``DISCOVERING``, uppercase — the original type was created in
b8951ce66d27 with uppercase labels ``'ACTIVE'``..``'UNKNOWN'``). A
hypervisor transitioning to ``HypervisorStatus.DISCOVERING`` therefore
binds ``'DISCOVERING'``, absent from the type — PostgreSQL raises
``InvalidTextRepresentation``.

This adds the correctly-cased ``'DISCOVERING'`` label. The stale
lowercase ``'discovering'`` value is intentionally left in place:
PostgreSQL cannot drop an enum value without recreating the type, and
an unused label is harmless.

Revision ID: d2f1a0c3e8b7
Revises: c8a1f0e2b4d6
Create Date: 2026-05-18

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d2f1a0c3e8b7"
down_revision: Union[str, None] = "c8a1f0e2b4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # Native ENUM types only exist on PostgreSQL; on other backends
        # the column is a plain VARCHAR and needs no migration.
        return
    # `ALTER TYPE ... ADD VALUE` cannot run inside a transaction block on
    # PostgreSQL < 12 — run it in an autocommit block.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE hypervisorstatus ADD VALUE IF NOT EXISTS 'DISCOVERING'"
        )


def downgrade() -> None:
    # PostgreSQL cannot remove a value from an enum type without
    # recreating it — intentionally a no-op (mirrors 53e5a25cf4d0).
    pass
