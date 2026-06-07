"""
Feature 002 — validation des configs cluster (T016).

kubeconfig (taille/forme), URL custom (SSRF), applicabilité du mode.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from app.models.cluster_config import ClusterMode, ClusterScopeType
from app.schemas.cluster_config import ClusterConfigUpsert
from app.services.cluster.validation import (
    InvalidKubeconfig,
    KubeconfigTooLarge,
    ModeNotApplicable,
    assert_mode_applicable,
    validate_kubeconfig_bytes,
)

_VALID_KUBECONFIG = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [{"name": "c", "cluster": {"server": "https://api.example.com:6443"}}],
    "contexts": [{"name": "ctx", "context": {"cluster": "c", "user": "u"}}],
    "users": [{"name": "u", "user": {"token": "abc"}}],
}


def _raw(doc: dict) -> bytes:
    return yaml.safe_dump(doc).encode("utf-8")


def test_valid_kubeconfig_accepted():
    parsed = validate_kubeconfig_bytes(_raw(_VALID_KUBECONFIG), max_bytes=1_000_000)
    assert parsed["apiVersion"] == "v1"


def test_oversized_kubeconfig_rejected():
    with pytest.raises(KubeconfigTooLarge):
        validate_kubeconfig_bytes(_raw(_VALID_KUBECONFIG), max_bytes=10)


def test_non_yaml_rejected():
    with pytest.raises(InvalidKubeconfig):
        validate_kubeconfig_bytes(b"\x00\x01 not yaml : : :", max_bytes=1_000_000)


def test_missing_keys_rejected():
    bad = {"apiVersion": "v1", "kind": "Config"}  # no clusters/contexts/users
    with pytest.raises(InvalidKubeconfig):
        validate_kubeconfig_bytes(_raw(bad), max_bytes=1_000_000)


@pytest.mark.parametrize("server", [
    "https://127.0.0.1:6443",
    "https://169.254.169.254:6443",
])
def test_kubeconfig_ssrf_server_rejected(server):
    # A kubeconfig whose cluster.server targets loopback / link-local must be
    # rejected with the same SSRF policy applied to custom-mode api_url.
    bad = {
        "apiVersion": "v1", "kind": "Config",
        "clusters": [{"name": "c", "cluster": {"server": server}}],
        "contexts": [{"name": "ctx", "context": {"cluster": "c", "user": "u"}}],
        "users": [{"name": "u", "user": {"token": "abc"}}],
    }
    with pytest.raises(InvalidKubeconfig):
        validate_kubeconfig_bytes(_raw(bad), max_bytes=1_000_000)


@pytest.mark.parametrize("host", ["https://127.0.0.1:6443", "https://169.254.169.254:6443", "::1", "0.0.0.0"])
def test_custom_url_ssrf_rejected(host):
    # IPv4 loopback/link-local are detected inside a URL; bare IPv6 loopback
    # and the unspecified address are detected as literal IPs (the existing
    # _check_host_not_ssrf guard does not parse unbracketed IPv6 from a URL).
    with pytest.raises(ValidationError):
        ClusterConfigUpsert(
            mode=ClusterMode.CUSTOM,
            api_url=host,
            token="t",
        )


def test_custom_url_normal_host_accepted():
    cfg = ClusterConfigUpsert(
        mode=ClusterMode.CUSTOM,
        api_url="https://api.migration.example.com:6443",
        token="t",
    )
    assert cfg.api_url.endswith(":6443")


def test_incluster_blocked_without_service_host(monkeypatch):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    with pytest.raises(ModeNotApplicable):
        assert_mode_applicable(ClusterScopeType.PLATFORM_DEFAULT, ClusterMode.INCLUSTER)


def test_incluster_blocked_for_tenant_scope(monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    with pytest.raises(ModeNotApplicable):
        assert_mode_applicable(ClusterScopeType.TENANT, ClusterMode.INCLUSTER)


def test_incluster_allowed_for_platform_default_in_cluster(monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    # Should not raise.
    assert_mode_applicable(ClusterScopeType.PLATFORM_DEFAULT, ClusterMode.INCLUSTER)
