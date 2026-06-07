"""
Feature 002 — CRUD de la configuration cluster (T015).

Couvre : round-trip CRUD + vault, bump de ``config_version``, ``record_health``
sans bump, émission d'audit append-only, et reversion d'override tenant.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import cluster_config as crud
from app.models.base import Base
from app.models.cluster_config import (
    ClusterConfigEvent,
    ClusterHealthStatus,
    ClusterMode,
    ClusterScopeType,
)
from app.schemas.cluster_config import ClusterConfigUpsert


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _custom_upsert(token: str = "bearer-secret") -> ClusterConfigUpsert:
    return ClusterConfigUpsert(
        mode=ClusterMode.CUSTOM,
        api_url="https://api.example.com:6443",
        token=token,
        verify_ssl=False,
        default_namespace="default",
    )


def test_upsert_custom_stores_ciphertext_and_bumps_version(db_session):
    row = crud.upsert(
        db_session,
        scope_type=ClusterScopeType.PLATFORM_DEFAULT,
        tenant_id=None,
        data=_custom_upsert("tok-1"),
        actor_user_id=None,
    )
    assert row.config_version == 1
    assert row.token_ciphertext is not None
    assert isinstance(row.token_ciphertext, (bytes, bytearray))
    assert crud.decrypt_token(row) == "tok-1"
    assert row.has_credentials is True

    # A second upsert bumps the version (cache-invalidation signal).
    row2 = crud.upsert(
        db_session,
        scope_type=ClusterScopeType.PLATFORM_DEFAULT,
        tenant_id=None,
        data=_custom_upsert("tok-2"),
        actor_user_id=None,
    )
    assert row2.config_version == 2
    assert crud.decrypt_token(row2) == "tok-2"


def test_set_kubeconfig_round_trip(db_session):
    raw = b"apiVersion: v1\nkind: Config\n"
    row = crud.set_kubeconfig(
        db_session,
        scope_type=ClusterScopeType.PLATFORM_DEFAULT,
        tenant_id=None,
        raw_bytes=raw,
        actor_user_id=7,
    )
    assert row.mode == ClusterMode.KUBECONFIG
    assert crud.decrypt_kubeconfig(row) == raw.decode("utf-8")
    assert row.token_ciphertext is None


def test_record_health_does_not_bump_version(db_session):
    row = crud.upsert(
        db_session,
        scope_type=ClusterScopeType.PLATFORM_DEFAULT,
        tenant_id=None,
        data=_custom_upsert(),
        actor_user_id=None,
    )
    version_before = row.config_version
    crud.record_health(db_session, row, ClusterHealthStatus.HEALTHY, "reachable")
    assert row.config_version == version_before
    assert row.health_status == ClusterHealthStatus.HEALTHY
    assert row.health_reason == "reachable"


def test_audit_event_emitted_on_apply(db_session):
    crud.upsert(
        db_session,
        scope_type=ClusterScopeType.PLATFORM_DEFAULT,
        tenant_id=None,
        data=_custom_upsert(),
        actor_user_id=42,
    )
    events = db_session.query(ClusterConfigEvent).all()
    assert len(events) == 1
    assert events[0].outcome == "applied"
    assert events[0].config_scope_type == "PLATFORM_DEFAULT"
    assert events[0].target_mode == "custom"


def test_delete_tenant_override_reverts_to_default(db_session):
    crud.upsert(
        db_session,
        scope_type=ClusterScopeType.TENANT,
        tenant_id="tenant-a",
        data=_custom_upsert(),
        actor_user_id=1,
    )
    assert crud.get_tenant_config(db_session, "tenant-a") is not None

    deleted = crud.delete_tenant_override(db_session, "tenant-a", actor_user_id=1)
    assert deleted is True
    assert crud.get_tenant_config(db_session, "tenant-a") is None

    # An audit row records the reversion.
    outcomes = [e.outcome for e in db_session.query(ClusterConfigEvent).all()]
    assert outcomes.count("applied") == 2  # upsert + delete
