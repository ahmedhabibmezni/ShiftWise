"""
ShiftWise Adapter — guest OS fixup stage.

Pipeline position:
    Discovery -> Analyzer -> Converter -> [Adapter] -> Migrator -> Reporting

Why this stage exists:
    A VM exported from VMware (or any source hypervisor) ships with guest
    config tightly bound to the source's hardware: NIC interface name
    (`ens33`, `eth0`, ...), serial console disabled, GRUB tuned for the
    source's display. After conversion qcow2 -> qcow2 the disk content is
    semantically identical — including all that source-specific config.

    On KubeVirt the guest sees virtio devices with names like `enp1s0`,
    `ens2`, etc. The old `/etc/network/interfaces ens33` no longer matches
    anything → no NIC comes up → VM boots fine but is unreachable.
    `virtctl console` shows nothing → invisible failure.

    The Adapter mutates the qcow2 IN PLACE on the transit volume to:
      - Drop a generic DHCP config that matches all common virtio NIC names
      - Enable `serial-getty@ttyS0` (so `virtctl console` works)
      - Tune GRUB to send kernel logs to ttyS0 too
      - SELinux relabel where applicable

    This is what `virt-v2v` does on Windows guests via the libguestfs
    Windows hooks. We do it explicitly for Linux because we run
    `qemu-img convert` directly on Linux disks (faster than virt-v2v) and
    therefore skip virt-v2v's fixup machinery.

Public entry point:
    from app.services.adapter.service import AdapterService
    AdapterService().run(db, migration_id)
"""

from app.services.adapter.service import AdapterService

__all__ = ["AdapterService"]
