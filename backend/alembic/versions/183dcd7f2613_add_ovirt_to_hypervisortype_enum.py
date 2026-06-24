"""add OVIRT to hypervisortype enum

The Python `HypervisorType` enum declares ten members (vSphere, VMware
Workstation, VMware ESXi, Hyper-V, KVM, Proxmox, oVirt, VirtualBox, Xen,
Other). The Postgres `hypervisortype` enum on databases initialised
before this revision is missing `OVIRT`, which crashed any INSERT on a
new oVirt hypervisor and any per-value COUNT (the hypervisor stats
endpoint hit this with `InvalidTextRepresentation`).

DUPLICATE NOTICE (audit H4): an earlier revision `f1a2b3c4d5e6`
("add ovirt value to hypervisortype enum", down_revision a9d8d838996f)
already adds the same `OVIRT` enum value, but on a different branch of
the revision graph and WITHOUT an `autocommit_block()` — which fails on
PostgreSQL < 12 because `ALTER TYPE ... ADD VALUE` cannot run inside a
transaction there. This revision supersedes `f1a2b3c4d5e6`: it is the
canonical, portable form. Both statements use `ADD VALUE IF NOT EXISTS`,
so applying both is harmless and idempotent. Neither migration is
deleted because at least one is already applied on existing databases.
Future readers: prefer this revision's pattern for additive enum changes.

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
