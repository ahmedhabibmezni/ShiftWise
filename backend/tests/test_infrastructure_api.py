"""
Feature 002 — endpoints Infrastructure (T017 / T025 / T031).

Les handlers sont appelés directement avec un ``User`` construit (même
pattern que ``test_reports_stats_rbac``) : ``check_permission`` (Depends) est
hors scope ; on teste le scoping tenant en corps de handler, la validation,
et la non-divulgation des secrets.
"""

from __future__ import annotations

import io

import pytest
import yaml
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import infrastructure as infra
from app.models.base import Base
from app.models.cluster_config import ClusterMode, ClusterScopeType
from app.models.user import User
from app.schemas.cluster_config import ClusterConfigUpsert


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _superuser() -> User:
    return User(
        email="su@example.com", username="su", hashed_password="x",
        tenant_id="ops", is_superuser=True,
    )


def _tenant_admin(tenant: str) -> User:
    return User(
        email=f"{tenant}@example.com", username=tenant, hashed_password="x",
        tenant_id=tenant, is_superuser=False,
    )


_VALID_KUBECONFIG = {
    "apiVersion": "v1", "kind": "Config",
    "clusters": [{"name": "c", "cluster": {"server": "https://api.example.com:6443"}}],
    "contexts": [{"name": "ctx", "context": {"cluster": "c", "user": "u"}}],
    "users": [{"name": "u", "user": {"token": "super-secret-kubeconfig-token"}}],
}


class _FakeUpload:
    """Imite ``UploadFile`` pour l'appel direct du handler."""

    def __init__(self, raw: bytes):
        self.file = io.BytesIO(raw)


# --- US1 : upload kubeconfig -------------------------------------------------

def test_upload_kubeconfig_superuser_ok_and_no_secret_leak(db_session):
    raw = yaml.safe_dump(_VALID_KUBECONFIG).encode("utf-8")
    result = infra.upload_kubeconfig(
        "platform-default", db_session, _superuser(), _FakeUpload(raw),
    )
    assert result.mode == ClusterMode.KUBECONFIG
    assert result.has_credentials is True

    # SC-004 — aucun secret du kubeconfig dans la réponse sérialisée.
    body = result.model_dump_json()
    assert "super-secret-kubeconfig-token" not in body
    assert "BEGIN" not in body  # pas de matériel de cert


def test_upload_oversized_rejected(db_session, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "CLUSTER_KUBECONFIG_MAX_BYTES", 10)
    raw = yaml.safe_dump(_VALID_KUBECONFIG).encode("utf-8")
    with pytest.raises(HTTPException) as exc:
        infra.upload_kubeconfig("platform-default", db_session, _superuser(), _FakeUpload(raw))
    assert exc.value.status_code == 413
    assert exc.value.detail["code"] == infra.ERR_KUBECONFIG_TOO_LARGE


def test_upload_malformed_rejected(db_session):
    with pytest.raises(HTTPException) as exc:
        infra.upload_kubeconfig(
            "platform-default", db_session, _superuser(), _FakeUpload(b"not a kubeconfig"),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == infra.ERR_INVALID_KUBECONFIG


# --- US2 : PUT mode + validation --------------------------------------------

def test_put_custom_success(db_session):
    payload = ClusterConfigUpsert(
        mode=ClusterMode.CUSTOM, api_url="https://api.example.com:6443",
        token="tok", verify_ssl=True, default_namespace="default",
    )
    result = infra.upsert_scope_config("platform-default", payload, db_session, _superuser())
    assert result.mode == ClusterMode.CUSTOM
    assert result.api_url == "https://api.example.com:6443"
    assert "tok" not in result.model_dump_json()


def test_put_incluster_blocked_without_service_host(db_session, monkeypatch):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    payload = ClusterConfigUpsert(mode=ClusterMode.INCLUSTER)
    with pytest.raises(HTTPException) as exc:
        infra.upsert_scope_config("platform-default", payload, db_session, _superuser())
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == infra.ERR_MODE_NOT_APPLICABLE


def test_put_incluster_blocked_for_tenant(db_session, monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    payload = ClusterConfigUpsert(mode=ClusterMode.INCLUSTER)
    with pytest.raises(HTTPException) as exc:
        infra.upsert_scope_config("tenant:ops", payload, db_session, _superuser())
    assert exc.value.status_code == 422


# --- US3 : scoping tenant + delete ------------------------------------------

def test_tenant_admin_can_access_own_scope(db_session):
    payload = ClusterConfigUpsert(
        mode=ClusterMode.CUSTOM, api_url="https://api.t.example.com:6443", token="t",
    )
    result = infra.upsert_scope_config("tenant:acme", payload, db_session, _tenant_admin("acme"))
    assert result.tenant_id == "acme"


def test_tenant_admin_denied_platform_default(db_session):
    payload = ClusterConfigUpsert(mode=ClusterMode.CUSTOM, api_url="https://x.example.com", token="t")
    with pytest.raises(HTTPException) as exc:
        infra.upsert_scope_config("platform-default", payload, db_session, _tenant_admin("acme"))
    assert exc.value.status_code == 403


def test_tenant_admin_denied_other_tenant(db_session):
    with pytest.raises(HTTPException) as exc:
        infra.get_scope_config("tenant:other", db_session, _tenant_admin("acme"))
    assert exc.value.status_code == 403


def test_list_scopes_tenant_admin_sees_only_own(db_session):
    result = infra.list_scopes(db_session, _tenant_admin("acme"))
    assert len(result.items) == 1
    assert result.items[0].tenant_id == "acme"
    assert result.items[0].using_platform_default is True


def test_list_scopes_superuser_sees_default_plus_tenants(db_session):
    infra.upsert_scope_config(
        "tenant:acme",
        ClusterConfigUpsert(mode=ClusterMode.CUSTOM, api_url="https://a.example.com", token="t"),
        db_session, _superuser(),
    )
    result = infra.list_scopes(db_session, _superuser())
    scope_types = {e.scope_type for e in result.items}
    assert ClusterScopeType.PLATFORM_DEFAULT in scope_types
    assert ClusterScopeType.TENANT in scope_types


def test_delete_platform_default_conflict(db_session):
    with pytest.raises(HTTPException) as exc:
        infra.delete_scope_config("platform-default", db_session, _superuser())
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == infra.ERR_CANNOT_DELETE_DEFAULT


def test_delete_tenant_override_reverts(db_session):
    infra.upsert_scope_config(
        "tenant:acme",
        ClusterConfigUpsert(mode=ClusterMode.CUSTOM, api_url="https://a.example.com", token="t"),
        db_session, _tenant_admin("acme"),
    )
    infra.delete_scope_config("tenant:acme", db_session, _tenant_admin("acme"))
    # After delete, the tenant view falls back to platform default.
    entry = infra.get_scope_config("tenant:acme", db_session, _tenant_admin("acme"))
    assert entry.using_platform_default is True
    assert entry.config is None
