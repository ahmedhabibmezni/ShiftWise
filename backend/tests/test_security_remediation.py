"""
Regression tests for the 2026-06 security remediation pass.

Each test pins one fix from `security-vulnerabilities-fix.md` so a future
change that reopens the hole fails CI.
"""

from __future__ import annotations

import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.security import decode_token, validate_password_strength
from app.crud import migration_event as crud_migration_event
from app.models.base import Base
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.migration_event import MigrationEventType
from app.services.cluster.validation import (
    InvalidKubeconfig,
    validate_kubeconfig_bytes,
)

_REQUIRED = {
    "DATABASE_HOST": "localhost",
    "DATABASE_NAME": "shiftwise_test",
    "DATABASE_USER": "user",
    "DATABASE_PASSWORD": "pw",
    "SECRET_KEY": "k" * 48,
    "SHIFTWISE_FERNET_KEY": "PJ8h2c0r1n8t1m3K3yF0rT3st1ngONLY0123456789a=",
}


def _settings(**overrides):
    # A valid Fernet key is required; generate one lazily so the test is
    # self-contained regardless of the ambient env.
    from cryptography.fernet import Fernet

    base = dict(_REQUIRED)
    base["SHIFTWISE_FERNET_KEY"] = Fernet.generate_key().decode()
    return Settings(_env_file=None, **{**base, **overrides})


# --- SV-003 — ALGORITHM allowlist ---------------------------------------

def test_sv003_algorithm_none_rejected():
    with pytest.raises(ValidationError):
        _settings(ALGORITHM="none")


@pytest.mark.parametrize("alg", ["RS256", "ES256", "HS999", ""])
def test_sv003_non_symmetric_algorithms_rejected(alg):
    with pytest.raises(ValidationError):
        _settings(ALGORITHM=alg)


@pytest.mark.parametrize("alg", ["HS256", "HS384", "HS512"])
def test_sv003_symmetric_algorithms_accepted(alg):
    assert _settings(ALGORITHM=alg).ALGORITHM == alg


# --- SV-004 — decode requires exp/sub/type ------------------------------

def test_sv004_token_without_exp_rejected():
    from app.core.config import settings

    token = jwt.encode(
        {"sub": "1", "type": "access"},  # no exp
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    assert decode_token(token) is None


def test_sv004_token_without_sub_rejected():
    from datetime import datetime, timedelta, timezone

    from app.core.config import settings

    token = jwt.encode(
        {
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    assert decode_token(token) is None


# --- SV-002 — kubeconfig exec credential plugin rejected -----------------

_EXEC_KUBECONFIG = b"""
apiVersion: v1
clusters:
- name: c
  cluster:
    server: https://cluster.example.com:6443
contexts:
- name: x
  context: {cluster: c, user: u}
current-context: x
users:
- name: u
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1
      command: /bin/sh
      args: ["-c", "id"]
"""

_CMDPATH_KUBECONFIG = b"""
apiVersion: v1
clusters:
- name: c
  cluster:
    server: https://cluster.example.com:6443
contexts:
- name: x
  context: {cluster: c, user: u}
current-context: x
users:
- name: u
  user:
    auth-provider:
      name: gcp
      config:
        cmd-path: /bin/sh
"""

_TOKEN_KUBECONFIG = b"""
apiVersion: v1
clusters:
- name: c
  cluster:
    server: https://cluster.example.com:6443
contexts:
- name: x
  context: {cluster: c, user: u}
current-context: x
users:
- name: u
  user:
    token: abc.def.ghi
"""


def test_sv002_kubeconfig_with_exec_rejected():
    with pytest.raises(InvalidKubeconfig):
        validate_kubeconfig_bytes(_EXEC_KUBECONFIG, max_bytes=1_048_576)


def test_sv002_kubeconfig_with_cmd_path_rejected():
    with pytest.raises(InvalidKubeconfig):
        validate_kubeconfig_bytes(_CMDPATH_KUBECONFIG, max_bytes=1_048_576)


def test_sv002_kubeconfig_with_token_accepted():
    doc = validate_kubeconfig_bytes(_TOKEN_KUBECONFIG, max_bytes=1_048_576)
    assert doc["users"][0]["user"]["token"] == "abc.def.ghi"


# --- SV-019 — password policy requires a special char everywhere ---------

def test_sv019_password_without_special_char_rejected():
    ok, _ = validate_password_strength("Abcdef123")  # no special char
    assert ok is False


def test_sv019_password_with_special_char_accepted():
    ok, msg = validate_password_strength("Abcdef123!")
    assert ok is True
    assert msg == ""


# --- SV-021 — audit-log hash chain detects tamper ------------------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_migration(db, tenant="t1"):
    mig = Migration(
        tenant_id=tenant, vm_id=1, status=MigrationStatus.PENDING,
        strategy=MigrationStrategy.AUTO, target_namespace=f"shiftwise-{tenant}",
    )
    db.add(mig)
    db.commit()
    return mig


def test_sv021_intact_chain_verifies(db_session):
    mig = _seed_migration(db_session)
    for i in range(3):
        crud_migration_event.record_event(
            db_session,
            migration_id=mig.id,
            tenant_id=mig.tenant_id,
            event_type=MigrationEventType.STAGE_EVENT,
            to_status=MigrationStatus.PENDING.value,
            message=f"step-{i}",
            commit=True,
        )
    ok, broken = crud_migration_event.verify_event_chain(db_session, mig.id)
    assert ok is True
    assert broken is None


def test_sv021_tampered_row_breaks_chain(db_session):
    mig = _seed_migration(db_session)
    events = []
    for i in range(3):
        events.append(
            crud_migration_event.record_event(
                db_session,
                migration_id=mig.id,
                tenant_id=mig.tenant_id,
                event_type=MigrationEventType.STAGE_EVENT,
                to_status=MigrationStatus.PENDING.value,
                message=f"step-{i}",
                commit=True,
            )
        )
    # Simulate an attacker editing the content of the middle row directly
    # (bypassing the append-only trigger, SV-001). The stored row_hash now
    # no longer matches the row content.
    tampered = events[1]
    tampered.message = "rewritten-by-attacker"
    db_session.commit()

    ok, broken = crud_migration_event.verify_event_chain(db_session, mig.id)
    assert ok is False
    assert broken == tampered.sequence_id


def test_sv021_deleted_row_breaks_chain(db_session):
    mig = _seed_migration(db_session)
    events = []
    for i in range(3):
        events.append(
            crud_migration_event.record_event(
                db_session,
                migration_id=mig.id,
                tenant_id=mig.tenant_id,
                event_type=MigrationEventType.STAGE_EVENT,
                to_status=MigrationStatus.PENDING.value,
                message=f"step-{i}",
                commit=True,
            )
        )
    # Delete the middle row (SQLite has no append-only trigger). The third
    # row's prev_hash no longer matches, so the chain breaks at seq 3.
    db_session.delete(events[1])
    db_session.commit()

    ok, broken = crud_migration_event.verify_event_chain(db_session, mig.id)
    assert ok is False
    assert broken == events[2].sequence_id
