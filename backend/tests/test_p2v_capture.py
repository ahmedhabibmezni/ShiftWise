from app.models.conversion import SourceFormat
from app.services.converter.connectors.physical import (
    PhysicalPuller,
    build_capture_command,
)


class _VM:
    def __init__(self, disks):
        self.custom_metadata = {"physical_disks": disks}
        self.name = "debian-p2v"


def test_list_disks_from_plan():
    vm = _VM([
        {"name": "sda", "device": "/dev/sda", "size_bytes": 8589934592, "is_boot": True},
        {"name": "sdb", "device": "/dev/sdb", "size_bytes": 4294967296, "is_boot": False},
    ])
    descriptors = PhysicalPuller().list_disks(hv=None, vm=vm)
    assert len(descriptors) == 2
    assert descriptors[0].disk_index == 0
    assert descriptors[0].locator == "/dev/sda"
    assert descriptors[0].source_format == SourceFormat.RAW
    assert descriptors[0].size_bytes == 8589934592
    assert descriptors[1].locator == "/dev/sdb"


def test_list_disks_empty_plan_raises():
    import pytest
    from app.services.converter.errors import ConversionError
    with pytest.raises(ConversionError) as exc:
        PhysicalPuller().list_disks(hv=None, vm=_VM([]))
    assert exc.value.code == "ERR_DISK_NOT_FOUND"


def test_build_capture_command_quotes_device():
    cmd = build_capture_command("/dev/sda")
    assert "dd if=/dev/sda bs=4M" in cmd
    assert "gzip -1" in cmd


def test_build_capture_command_rejects_injection():
    cmd = build_capture_command("/dev/sda; rm -rf /")
    assert cmd.startswith("dd if='/dev/sda; rm -rf /'")


import gzip as _gzip


def hashlib_sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def test_stream_gunzip_to_file(tmp_path):
    from app.services.converter.connectors.physical import _stream_gunzip_to_file

    payload = b"SHIFTWISE-RAW-DISK-CONTENT" * 1000
    compressed = _gzip.compress(payload)

    class _Chan:
        def __init__(self, data): self._buf = data
        def read(self, n=-1):
            if not self._buf:
                return b""
            take, self._buf = self._buf[:7], self._buf[7:]
            return take

    dest = tmp_path / "0.raw"
    progress = []
    sha = _stream_gunzip_to_file(
        _Chan(compressed), dest, expected_size=len(payload),
        progress_cb=lambda d, t: progress.append((d, t)),
    )
    assert dest.read_bytes() == payload
    assert sha == hashlib_sha(payload)
    assert progress


def test_local_raw_to_qcow2_invokes_qemu_img(tmp_path, monkeypatch):
    from app.services.converter.connectors import physical

    raw = tmp_path / "0.raw"
    raw.write_bytes(b"x" * 4096)
    out = tmp_path / "0.qcow2"

    calls = {}

    def fake_run(cmd, check, capture_output, text):
        calls["cmd"] = cmd
        out.write_bytes(b"qcow2-bytes")
        class _R:
            returncode = 0
            stderr = ""
        return _R()

    monkeypatch.setattr(physical.subprocess, "run", fake_run)
    physical._local_raw_to_qcow2(raw, out)

    assert calls["cmd"][:3] == ["qemu-img", "convert", "-O"]
    assert "qcow2" in calls["cmd"]
    assert "-c" in calls["cmd"]
    assert out.exists()


def test_physical_puller_conforms_to_protocol():
    from app.services.converter.protocol import DiskPuller
    from app.services.converter.connectors.physical import PhysicalPuller
    p: DiskPuller = PhysicalPuller()
    assert all(hasattr(p, m) for m in ("list_disks", "pull_disk", "convert_on_source"))


def test_registry_returns_physical_puller():
    from app.models.hypervisor import HypervisorType
    from app.services.converter.connectors import get_puller
    from app.services.converter.connectors.physical import PhysicalPuller

    puller = get_puller(HypervisorType.PHYSICAL)
    assert isinstance(puller, PhysicalPuller)
