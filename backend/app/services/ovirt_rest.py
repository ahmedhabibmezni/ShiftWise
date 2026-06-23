"""
SDK-free oVirt / RHV REST client.

``ovirt-engine-sdk-python`` is a native C-extension package (it links against
libxml2) and cannot be pip-installed on a Windows worker. The dev/demo topology
runs the Celery worker on a Windows laptop that is the only host able to reach
the oVirt engine (the cluster cannot), so the SDK path is unusable there.

This module talks to the engine over plain HTTPS + JSON using ``requests`` with
HTTP Basic auth — every control-plane operation the discovery service and the
converter need (list VMs, disk attachments, disks, reported devices, power
stop/start, and ImageTransfer download) has a documented REST equivalent. It is
used as a fallback whenever ``ovirtsdk4`` is not importable; in-cluster (Linux,
SDK present) the existing SDK path is unchanged.

oVirt JSON quirks handled here:
  * collections wrap in a singular key (``{"vm": [...]}``) and the key is absent
    when empty;
  * a single-element collection may be returned as an object, not a list;
  * numeric fields are inconsistently typed — ``memory`` is a JSON number but
    ``cpu.topology.cores`` is a JSON string — so callers must coerce via
    :func:`to_int`.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, Optional

from app.models.hypervisor import Hypervisor

logger = logging.getLogger(__name__)

_DEFAULT_API_PATH = "/ovirt-engine/api"


def ovirt_sdk_available() -> bool:
    """True iff ``ovirt-engine-sdk-python`` is importable in this worker."""
    try:
        import ovirtsdk4  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def to_int(value: Any, default: int = 0) -> int:
    """Coerce an oVirt JSON scalar (number or stringly-typed) to ``int``."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_base_url(hv: Hypervisor) -> str:
    """Build the engine API base URL from the hypervisor row."""
    cfg = hv.connection_config or {}
    host = hv.host or "localhost"
    api_path = cfg.get("api_path") or _DEFAULT_API_PATH
    port = f":{hv.port}" if hv.port else ""
    return f"https://{host}{port}{api_path}"


class OvirtRestError(Exception):
    """Any failure talking to the oVirt REST API."""

    def __init__(self, message: str, *, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _as_list(payload: Optional[dict], key: str) -> list:
    """Unwrap an oVirt collection payload to a plain list.

    ``{"vm": [...]}`` -> the list; ``{"vm": {...}}`` -> ``[{...}]``; missing key
    or empty payload -> ``[]``.
    """
    if not payload:
        return []
    val = payload.get(key)
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


class OvirtRestClient:
    """Thin JSON+Basic-auth client over the oVirt engine REST API."""

    def __init__(self, hv: Hypervisor, *, timeout: int = 60):
        import requests  # type: ignore

        cfg = hv.connection_config or {}
        self._base = build_base_url(hv).rstrip("/")
        self._timeout = timeout
        self._host = hv.host
        ca_file = cfg.get("ca_file") or hv.ssl_cert_path or None
        # Verify against the CA bundle when one is supplied and verification is
        # on; otherwise honour the (dev) insecure flag.
        self._verify: object = ca_file if (hv.verify_ssl and ca_file) else bool(hv.verify_ssl)

        password = hv.password_plain
        if not password:
            raise OvirtRestError(f"No usable credential for oVirt engine {hv.host}")

        self._session = requests.Session()
        self._session.auth = (hv.username or "admin@internal", password)
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            # Reuse one SSO session across requests instead of minting one per
            # call (oVirt leaks ephemeral sessions otherwise).
            "Prefer": "persistent-auth",
        })

    # --- low level ---------------------------------------------------------

    def _request(self, method: str, path: str, *, json_body: Optional[dict] = None) -> dict:
        import requests  # type: ignore

        url = path if path.startswith("http") else f"{self._base}{path}"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # insecure-TLS warning is intentional in dev
                resp = self._session.request(
                    method, url, json=json_body, verify=self._verify, timeout=self._timeout,
                )
        except requests.RequestException as e:  # NOSONAR — network failure surface
            raise OvirtRestError(f"oVirt REST {method} {path} failed: {e}") from e
        if resp.status_code >= 400:
            raise OvirtRestError(
                f"oVirt REST {method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}",
                status=resp.status_code,
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, json_body=body)

    # --- high level --------------------------------------------------------

    def list_vms(self) -> list:
        return _as_list(self.get("/vms?all_content=true"), "vm")

    def get_vm(self, vm_id: str) -> dict:
        return self.get(f"/vms/{vm_id}")

    def vm_status(self, vm_id: str) -> str:
        return str((self.get_vm(vm_id) or {}).get("status") or "")

    def list_disk_attachments(self, vm_id: str) -> list:
        return _as_list(self.get(f"/vms/{vm_id}/diskattachments"), "disk_attachment")

    def get_disk(self, disk_id: str) -> dict:
        return self.get(f"/disks/{disk_id}")

    def list_reported_devices(self, vm_id: str) -> list:
        return _as_list(self.get(f"/vms/{vm_id}/reporteddevices"), "reported_device")

    def stop_vm(self, vm_id: str) -> None:
        self.post(f"/vms/{vm_id}/stop", {})

    def start_vm(self, vm_id: str) -> None:
        self.post(f"/vms/{vm_id}/start", {})

    def start_image_transfer(self, disk_id: str, direction: str = "download") -> dict:
        return self.post(
            "/imagetransfers",
            {"disk": {"id": disk_id}, "direction": direction},
        )

    def get_image_transfer(self, transfer_id: str) -> dict:
        return self.get(f"/imagetransfers/{transfer_id}")

    def finalize_image_transfer(self, transfer_id: str) -> None:
        self.post(f"/imagetransfers/{transfer_id}/finalize", {})

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # NOSONAR — best-effort close
            logger.debug("oVirt REST session close failed", exc_info=True)
