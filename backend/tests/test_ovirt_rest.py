"""Unit tests for the SDK-free oVirt REST client (app/services/ovirt_rest.py)."""

import json

import pytest

from app.services.ovirt_rest import (
    OvirtRestClient,
    OvirtRestError,
    _as_list,
    build_base_url,
    to_int,
)


class _HV:
    def __init__(self, **kw):
        self.host = kw.get("host", "manager.engine.local")
        self.port = kw.get("port")
        self.username = kw.get("username", "admin@internal")
        self.password_plain = kw.get("password_plain", "root")
        self.verify_ssl = kw.get("verify_ssl", False)
        self.ssl_cert_path = kw.get("ssl_cert_path")
        self.connection_config = kw.get("connection_config", {})


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = b"x" if payload is not None or text else b""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeSession:
    """Records requests and replays a queue of canned responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.headers = {}
        self.auth = None

    def request(self, method, url, json=None, verify=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "verify": verify})
        return self._responses.pop(0)

    def close(self):
        self.closed = True


def _client(hv=None, responses=()):
    c = OvirtRestClient(hv or _HV())
    c._session = _FakeSession(responses)
    return c


# --- pure helpers ----------------------------------------------------------

class TestHelpers:
    def test_to_int_number_and_string_and_default(self):
        assert to_int(536870912) == 536870912
        assert to_int("1") == 1
        assert to_int(None) == 0
        assert to_int("nope", default=7) == 7

    def test_as_list_unwraps_list_object_and_missing(self):
        assert _as_list({"vm": [{"id": "1"}, {"id": "2"}]}, "vm") == [{"id": "1"}, {"id": "2"}]
        # single element returned as an object, not a list
        assert _as_list({"vm": {"id": "1"}}, "vm") == [{"id": "1"}]
        assert _as_list({}, "vm") == []
        assert _as_list(None, "vm") == []

    def test_build_base_url_variants(self):
        assert build_base_url(_HV()) == "https://manager.engine.local/ovirt-engine/api"
        assert build_base_url(_HV(port=8443)) == "https://manager.engine.local:8443/ovirt-engine/api"
        assert build_base_url(
            _HV(connection_config={"api_path": "/api"})
        ) == "https://manager.engine.local/api"


# --- client ----------------------------------------------------------------

class TestOvirtRestClient:
    def test_missing_credential_raises(self):
        with pytest.raises(OvirtRestError):
            OvirtRestClient(_HV(password_plain=None))

    def test_basic_auth_and_json_headers(self):
        real = OvirtRestClient(_HV())
        assert real._session.auth == ("admin@internal", "root")
        assert real._session.headers["Accept"] == "application/json"

    def test_list_vms_unwraps_collection(self):
        c = _client(responses=[_Resp(payload={"vm": [{"id": "a"}, {"id": "b"}]})])
        vms = c.list_vms()
        assert [v["id"] for v in vms] == ["a", "b"]
        assert c._session.calls[0]["url"].endswith("/vms?all_content=true")

    def test_get_disk_path(self):
        c = _client(responses=[_Resp(payload={"id": "d1", "format": "cow"})])
        disk = c.get_disk("d1")
        assert disk["format"] == "cow"
        assert c._session.calls[0]["url"].endswith("/disks/d1")

    def test_http_error_raises_with_status(self):
        c = _client(responses=[_Resp(status_code=404, text="not found")])
        with pytest.raises(OvirtRestError) as ei:
            c.get_vm("missing")
        assert ei.value.status == 404

    def test_start_image_transfer_posts_body(self):
        c = _client(responses=[_Resp(payload={"id": "t1", "phase": "initializing"})])
        out = c.start_image_transfer("disk-9", "download")
        assert out["id"] == "t1"
        call = c._session.calls[0]
        assert call["method"] == "POST"
        assert call["json"] == {"disk": {"id": "disk-9"}, "direction": "download"}

    def test_stop_and_start_vm_endpoints(self):
        c = _client(responses=[_Resp(payload={}), _Resp(payload={})])
        c.stop_vm("vm-1")
        c.start_vm("vm-1")
        assert c._session.calls[0]["url"].endswith("/vms/vm-1/stop")
        assert c._session.calls[1]["url"].endswith("/vms/vm-1/start")

    def test_empty_body_returns_empty_dict(self):
        c = _client(responses=[_Resp(status_code=200, payload=None, text="")])
        assert c.finalize_image_transfer("t1") is None  # POST with empty 200

    def test_vm_status_reads_status_field(self):
        c = _client(responses=[_Resp(payload={"id": "v", "status": "up"})])
        assert c.vm_status("v") == "up"
