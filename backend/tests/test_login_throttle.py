"""
Tests for the login-throttle helper and its wiring into /auth/login.

Two layers:
- Unit tests on app.core.login_throttle, against a fakeredis instance
  (real Redis semantics, no broker needed).
- Integration tests via TestClient that confirm /auth/login returns 429
  with Retry-After once the threshold is crossed, and that a successful
  login clears the counters.
"""

from __future__ import annotations

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import auth as auth_module
from app.core import login_throttle
from app.core import redis_client as redis_client_module
from app.core.database import get_db
from app.core.security import get_password_hash
from app.main import app
from app.models.base import Base
from app.models.user import User


@pytest.fixture
def fake_redis(monkeypatch):
    """A fresh in-memory Redis bound into every site that calls get_redis().

    Both login_throttle and refresh_token_store do
    ``from app.core.redis_client import get_redis`` at module-import time,
    which binds the symbol into THEIR namespace. Patching only the source
    module misses those local references and lets the test hit a real
    Redis if one happens to be listening on localhost — accidental
    state-sharing was the original symptom that surfaced this fixture.
    Patch every consumer site explicitly.
    """
    server = fakeredis.FakeServer()
    client = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    factory = lambda: client

    monkeypatch.setattr(redis_client_module, "get_redis", factory)
    monkeypatch.setattr(login_throttle, "get_redis", factory)

    # refresh_token_store imports get_redis the same way; patch it too so
    # the auth-store doesn't accidentally talk to a real broker either.
    from app.core import refresh_token_store as _rts

    monkeypatch.setattr(_rts, "get_redis", factory)

    yield client
    client.flushall()


@pytest.fixture
def patch_settings(monkeypatch):
    from app.core import config as _config

    def _set(max_attempts: int, window_seconds: int):
        monkeypatch.setattr(_config.settings, "LOGIN_THROTTLE_MAX_ATTEMPTS", max_attempts)
        monkeypatch.setattr(_config.settings, "LOGIN_THROTTLE_WINDOW_SECONDS", window_seconds)

    return _set


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestLoginThrottleHelper:

    def test_returns_none_when_disabled(self, fake_redis, patch_settings):
        patch_settings(max_attempts=0, window_seconds=60)
        for _ in range(10):
            login_throttle.record_failure("a@x", "1.1.1.1")
        assert login_throttle.check_lockout("a@x", "1.1.1.1") is None

    def test_locks_out_after_threshold_on_email(self, fake_redis, patch_settings):
        patch_settings(max_attempts=3, window_seconds=60)
        for _ in range(3):
            login_throttle.record_failure("a@x", None)
        result = login_throttle.check_lockout("a@x", None)
        assert result is not None
        assert result.locked_by == "email"
        assert 0 < result.retry_after_seconds <= 60

    def test_locks_out_after_threshold_on_ip(self, fake_redis, patch_settings):
        patch_settings(max_attempts=3, window_seconds=60)
        # Different emails — only the IP bucket should accumulate.
        for i in range(3):
            login_throttle.record_failure(f"u{i}@x", "9.9.9.9")
        result = login_throttle.check_lockout("brand-new@x", "9.9.9.9")
        assert result is not None
        assert result.locked_by == "ip"

    def test_email_lockout_is_case_insensitive(self, fake_redis, patch_settings):
        patch_settings(max_attempts=2, window_seconds=60)
        login_throttle.record_failure("Alice@Example.com", None)
        login_throttle.record_failure("alice@example.com", None)
        # Same bucket — should be locked.
        assert login_throttle.check_lockout("ALICE@example.com", None) is not None

    def test_reset_clears_both_buckets(self, fake_redis, patch_settings):
        patch_settings(max_attempts=3, window_seconds=60)
        for _ in range(3):
            login_throttle.record_failure("a@x", "1.1.1.1")
        assert login_throttle.check_lockout("a@x", "1.1.1.1") is not None
        login_throttle.reset("a@x", "1.1.1.1")
        assert login_throttle.check_lockout("a@x", "1.1.1.1") is None

    def test_locked_by_email_and_ip_when_both_over_threshold(
        self, fake_redis, patch_settings,
    ):
        patch_settings(max_attempts=2, window_seconds=60)
        login_throttle.record_failure("a@x", "1.1.1.1")
        login_throttle.record_failure("a@x", "1.1.1.1")
        result = login_throttle.check_lockout("a@x", "1.1.1.1")
        assert result is not None
        assert result.locked_by == "email+ip"

    def test_unrelated_email_or_ip_is_unaffected(self, fake_redis, patch_settings):
        patch_settings(max_attempts=3, window_seconds=60)
        for _ in range(3):
            login_throttle.record_failure("victim@x", "1.1.1.1")
        # Different email + different IP → still allowed.
        assert login_throttle.check_lockout("other@x", "2.2.2.2") is None


# ---------------------------------------------------------------------------
# /auth/login integration
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
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
    monkeypatch.setattr(auth_module, "_mint_refresh", lambda user_id: "fake-refresh-jwt")
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


class TestLoginThrottleIntegration:

    def test_returns_429_after_threshold_failures(
        self, fake_redis, patch_settings, db_session, alice,
    ):
        patch_settings(max_attempts=3, window_seconds=60)
        app.dependency_overrides[get_db] = _override_db(db_session)
        client = TestClient(app)

        for _ in range(3):
            r = client.post(
                "/api/v1/auth/login",
                json={"email": alice.email, "password": "wrong"},
            )
            assert r.status_code == 401

        # 4th attempt — even with the correct password — must be 429.
        r = client.post(
            "/api/v1/auth/login",
            json={"email": alice.email, "password": "CorrectHorse9!"},
        )
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        assert int(r.headers["Retry-After"]) > 0

    def test_success_clears_the_counter(
        self, fake_redis, patch_settings, db_session, alice,
    ):
        """Two typos followed by the right password should NOT leave a
        ticking time-bomb in Redis for the next legitimate login."""
        patch_settings(max_attempts=5, window_seconds=60)
        app.dependency_overrides[get_db] = _override_db(db_session)
        client = TestClient(app)

        for _ in range(2):
            r = client.post(
                "/api/v1/auth/login",
                json={"email": alice.email, "password": "wrong"},
            )
            assert r.status_code == 401

        r = client.post(
            "/api/v1/auth/login",
            json={"email": alice.email, "password": "CorrectHorse9!"},
        )
        assert r.status_code == 200

        # Counter should be cleared — proven by the throttle helper.
        assert login_throttle.check_lockout(alice.email, None) is None

    def test_lockout_does_not_call_authenticate(
        self, fake_redis, patch_settings, db_session, alice, monkeypatch,
    ):
        """Once locked out, even a correct password must short-circuit
        before bcrypt — so an attacker can't amplify DoS by paying the
        verification cost on every locked-out attempt."""
        patch_settings(max_attempts=2, window_seconds=60)
        app.dependency_overrides[get_db] = _override_db(db_session)
        client = TestClient(app)

        # Push the email bucket over the line.
        for _ in range(2):
            client.post(
                "/api/v1/auth/login",
                json={"email": alice.email, "password": "wrong"},
            )

        from app.crud import user as crud_user

        called = {"count": 0}
        real_authenticate = crud_user.authenticate_user

        def _spy(*args, **kwargs):
            called["count"] += 1
            return real_authenticate(*args, **kwargs)

        monkeypatch.setattr(crud_user, "authenticate_user", _spy)

        r = client.post(
            "/api/v1/auth/login",
            json={"email": alice.email, "password": "CorrectHorse9!"},
        )
        assert r.status_code == 429
        assert called["count"] == 0
