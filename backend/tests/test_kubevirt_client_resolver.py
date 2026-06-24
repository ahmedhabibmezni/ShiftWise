"""
Feature 002 — resolver de config effective + sonde de connexion (T026 / T032).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kubernetes.client.rest import ApiException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import cluster_config as crud
from app.models.base import Base
from app.models.cluster_config import (
    ClusterHealthStatus,
    ClusterMode,
    ClusterScopeType,
)
from app.schemas.cluster_config import ClusterConfigUpsert
from app.services.cluster import resolver


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed(db, scope_type, tenant_id):
    return crud.upsert(
        db,
        scope_type=scope_type,
        tenant_id=tenant_id,
        data=ClusterConfigUpsert(
            mode=ClusterMode.CUSTOM, api_url="https://api.example.com:6443", token="t",
        ),
        actor_user_id=None,
    )


def test_resolve_prefers_tenant_then_default(db_session):
    _seed(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    _seed(db_session, ClusterScopeType.TENANT, "acme")

    own = resolver.resolve_effective_config(db_session, "acme")
    assert own.scope_type == ClusterScopeType.TENANT

    fallback = resolver.resolve_effective_config(db_session, "no-override")
    assert fallback.scope_type == ClusterScopeType.PLATFORM_DEFAULT


def test_resolve_reverts_to_default_after_delete(db_session):
    _seed(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    _seed(db_session, ClusterScopeType.TENANT, "acme")
    crud.delete_tenant_override(db_session, "acme", actor_user_id=None)

    eff = resolver.resolve_effective_config(db_session, "acme")
    assert eff.scope_type == ClusterScopeType.PLATFORM_DEFAULT


def test_resolve_none_when_unconfigured(db_session):
    assert resolver.resolve_effective_config(db_session, "acme") is None


def _patch_client(monkeypatch, *, list_namespace_side):
    fake_client = MagicMock()
    fake_client.core_api.list_namespace.side_effect = list_namespace_side
    monkeypatch.setattr(
        resolver, "KubeVirtClient", lambda *a, **k: fake_client,
    )
    return fake_client


def test_connection_test_healthy(db_session, monkeypatch):
    _seed(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    ns = MagicMock()
    ns.items = [object(), object()]
    _patch_client(monkeypatch, list_namespace_side=lambda **k: ns)

    result = resolver.run_connection_test(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    assert result.status == ClusterHealthStatus.HEALTHY
    assert result.namespace_count == 2


def test_connection_test_auth_failed(db_session, monkeypatch):
    _seed(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    _patch_client(
        monkeypatch,
        list_namespace_side=ApiException(status=401, reason="Unauthorized"),
    )
    result = resolver.run_connection_test(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    assert result.status == ClusterHealthStatus.AUTH_FAILED


def test_connection_test_unreachable(db_session, monkeypatch):
    _seed(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    _patch_client(
        monkeypatch,
        list_namespace_side=ConnectionError("connection refused"),
    )
    result = resolver.run_connection_test(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    assert result.status == ClusterHealthStatus.UNREACHABLE


def test_connection_test_persists_health(db_session, monkeypatch):
    cfg = _seed(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    version_before = cfg.config_version
    ns = MagicMock()
    ns.items = []
    _patch_client(monkeypatch, list_namespace_side=lambda **k: ns)

    resolver.run_connection_test(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    db_session.refresh(cfg)
    assert cfg.health_status == ClusterHealthStatus.HEALTHY
    # Health write must NOT bump the config version.
    assert cfg.config_version == version_before


def test_no_config_to_test_returns_invalid(db_session):
    result = resolver.run_connection_test(db_session, ClusterScopeType.PLATFORM_DEFAULT, None)
    assert result.status == ClusterHealthStatus.INVALID
