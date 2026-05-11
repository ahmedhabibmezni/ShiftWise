"""add OVIRT to hypervisortype enum

The Python `HypervisorType` enum declares ten members (vSphere, VMware
Workstation, VMware ESXi, Hyper-V, KVM, Proxmox, oVirt, VirtualBox, Xen,
Other). The Postgres `hypervisortype` enum on databases initialised
before this revision is missing `OVIRT`, which crashed any INSERT on a
new oVirt hypervisor and any per-value COUNT (the hypervisor stats
endpoint hit this with `InvalidTextRepresentation`).

Revision ID: 183dcd7f2613
Revises: c7d2e8f4a1b3
Create Date: 2026-05-11 02:49:23.570008
"""
from typing import Sequence, Union

from alembic import op


revision: str = '183dcd7f2613'
down_revision: Union[str, None] = 'c7d2e8f4a1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on
    # PostgreSQL < 12; we are on PG 18 in dev and PG >= 14 on the cluster,
    # but the autocommit block keeps the migration portable. IF NOT EXISTS
    # makes it idempotent in case the value was patched in by hand.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE hypervisortype ADD VALUE IF NOT EXISTS 'OVIRT'")


def downgrade() -> None:
    # PostgreSQL has no native DROP VALUE on enums; rolling back this
    # change would require recreating the type, dropping any row that
    # uses OVIRT, and switching the column over. Not worth the risk for
    # an additive change. Documented limitation of PG enum types.
    pass
