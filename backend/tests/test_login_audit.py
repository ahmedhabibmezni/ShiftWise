"""
Tests for the /auth/login audit-trail wiring.

Confirms that a successful login stamps `last_login_at` and
`last_login_ip` on the User row, that a failed login does NOT, and that
a missing `request.client` (rare but possible during certain test
configurations) leaves `last_login_ip` as None instead of crashing.

The Redis-backed refresh family store is patched out so the suite
doesn't need a live broker.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import auth as auth_module
from app.core.database import get_db
from app.core.security import get_password_hash
from app.main import app
from app.models.base import Base
from app.models.user import User


@pytest.fixture
def db_session():
    # StaticPool + check_same_thread=False is the standard recipe for
    # exposing one in-memory SQLite database to both the test thread
    # (creating the fixture) and Starlette's thread-pool worker (running
    # the endpoint via TestClient). Without it the worker sees an empty
    # DB and CRUD looks broken.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session: Session = SessionFactory()
    yield session
    session.close()


@pytest.fixture
def alice(db_session: Session) -> User:
    user = User(
        email="alice@example.com",
        username="alice",
        hashed_password=get_password_hash("CorrectHorse9!"),
        tenant_id="t1",
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(autouse=True)
def _patch_refresh_store(monkeypatch):
    """Stub the Redis-backed family store. The audit fields live on the
    User row before any token-minting happens, so we don't care about
    actual refresh-cookie semantics in these tests."""
    monkeypatch.setattr(
        auth_module, "_mint_refresh", lambda user_id: "fake-refresh-jwt",
    )
    monkeypatch.setattr(
        auth_module,
        "_issue_access_token",
        lambda user_id: auth_module.TokenResponse(
            access_token="fake-access", token_type="bearer", expires_in=900,
        ),
    )
    yield
    app.dependency_overrides.clear()


def _override_db(session: Session):
    def _gen():
        yield session

    return _gen


def test_successful_login_stamps_last_login_at_and_ip(db_session, alice):
    app.dependency_overrides[get_db] = _override_db(db_session)
    client = TestClient(app)

    before = datetime.utcnow()
    response = client.post(
        "/api/v1/auth/login",
        json={"email": alice.email, "password": "CorrectHorse9!"},
    )
    after = datetime.utcnow()

    assert response.status_code == 200
    db_session.refresh(alice)
    assert alice.last_login_at is not None
    # SQLite strips tzinfo on round-trip, so compare against UTC-naive
    # bounds with a small slack window — TestClient is in-process so the
    # delta is sub-second, but pytest scheduling can stretch it.
    stamped = alice.last_login_at.replace(tzinfo=None)
    assert before - timedelta(seconds=2) <= stamped <= after + timedelta(seconds=2)
    # The IP is best-effort. Depending on starlette's TestClient
    # version it's either a string ("testclient" / "127.0.0.1") or None
    # when request.client wasn't populated. Both are acceptable shapes;
    # the dedicated truncation + None tests below pin the column
    # invariants.
    assert alice.last_login_ip is None or len(alice.last_login_ip) <= 45


def test_failed_login_leaves_audit_columns_untouched(db_session, alice):
    """Wrong password → 401 and the audit fields stay None."""
    app.dependency_overrides[get_db] = _override_db(db_session)
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": alice.email, "password": "WrongPassword1!"},
    )

    assert response.status_code == 401
    db_session.refresh(alice)
    assert alice.last_login_at is None
    assert alice.last_login_ip is None


def test_inactive_account_does_not_stamp_audit_columns(db_session, alice):
    """Inactive accounts return 403 — we shouldn't reward a half-success
    by stamping the audit trail (it would otherwise mask a brute-force
    attempt against a disabled account)."""
    alice.is_active = False
    db_session.commit()

    app.dependency_overrides[get_db] = _override_db(db_session)
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": alice.email, "password": "CorrectHorse9!"},
    )

    assert response.status_code == 403
    db_session.refresh(alice)
    assert alice.last_login_at is None
    assert alice.last_login_ip is None


def test_client_ip_truncates_to_45_chars(db_session, alice, monkeypatch):
    """Forged absurdly-long X-Forwarded-For (after a misconfigured proxy
    rewrites request.client.host) must not blow up the VARCHAR(45)
    column. The handler truncates defensively."""
    app.dependency_overrides[get_db] = _override_db(db_session)

    # Replace the helper so we don't have to fake a proxy stack.
    long_ip = "X" * 200
    monkeypatch.setattr(auth_module, "_client_ip", lambda _request: long_ip)

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": alice.email, "password": "CorrectHorse9!"},
    )

    assert response.status_code == 200
    db_session.refresh(alice)
    assert alice.last_login_ip is not None
    assert len(alice.last_login_ip) == 45


def test_missing_request_client_yields_null_ip(db_session, alice, monkeypatch):
    """If starlette can't determine request.client (unusual but possible),
    the audit row stamps the timestamp and leaves the IP as None."""
    app.dependency_overrides[get_db] = _override_db(db_session)
    monkeypatch.setattr(auth_module, "_client_ip", lambda _request: None)

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": alice.email, "password": "CorrectHorse9!"},
    )

    assert response.status_code == 200
    db_session.refresh(alice)
    assert alice.last_login_at is not None
    assert alice.last_login_ip is None
