"""
Unit tests for the `/health` probe.

Exercise the three documented states from `app.main.health_check`:
- healthy  : DB + Redis both up                 → HTTP 200
- degraded : DB up, Redis down                  → HTTP 200
- unhealthy: DB down (Redis state irrelevant)   → HTTP 503

Both dependencies are mocked at the FastAPI/dep-injection layer so the
suite never has to talk to a live Postgres or Redis instance.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.database import get_db
from app.main import app


class _StubDB:
    """Just enough of a SQLAlchemy Session for `.execute(text("SELECT 1"))`.

    Two modes:
      - mode="ok": execute() returns (real result is unused).
      - mode="down": execute() raises OperationalError, mirroring what a real
        driver does when the TCP connection drops.
    """

    def __init__(self, mode: str = "ok"):
        self.mode = mode

    def execute(self, _stmt):  # noqa: D401 — protocol stub
        if self.mode == "down":
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        return self

    def close(self):
        pass


def _override_db(mode: str):
    def _gen():
        yield _StubDB(mode=mode)
    return _gen


class _FakeRedis:
    """Stand-in for redis.Redis. `mode="down"` raises on PING."""

    def __init__(self, mode: str = "ok"):
        self.mode = mode

    def ping(self) -> bool:
        if self.mode == "down":
            raise ConnectionError("Connection refused")
        return True


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Reset the FastAPI dependency overrides between tests so one mode
    can't leak into the next case."""
    yield
    app.dependency_overrides.clear()


def test_health_healthy_when_both_dependencies_up(monkeypatch):
    app.dependency_overrides[get_db] = _override_db("ok")
    # The /health body imports app.core.redis_client lazily, so patching
    # the module attribute is enough — no need to swap a singleton.
    import app.core.redis_client as redis_module

    monkeypatch.setattr(redis_module, "get_redis", lambda: _FakeRedis(mode="ok"))

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["redis_auth"]["ok"] is True
    assert body["checks"]["database"]["error"] is None
    assert body["checks"]["redis_auth"]["error"] is None


def test_health_degraded_when_redis_is_down(monkeypatch):
    app.dependency_overrides[get_db] = _override_db("ok")
    import app.core.redis_client as redis_module

    monkeypatch.setattr(redis_module, "get_redis", lambda: _FakeRedis(mode="down"))

    client = TestClient(app)
    response = client.get("/health")

    # Degraded stays at 200 — the load balancer keeps the pod, an alert pages
    # the operator. Read-only endpoints can still serve.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["redis_auth"]["ok"] is False
    assert "ConnectionError" in body["checks"]["redis_auth"]["error"]


def test_health_unhealthy_when_database_is_down(monkeypatch):
    app.dependency_overrides[get_db] = _override_db("down")
    import app.core.redis_client as redis_module

    # Redis state is irrelevant once the DB is down — verify the endpoint
    # still completes (no exception) and returns 503.
    monkeypatch.setattr(redis_module, "get_redis", lambda: _FakeRedis(mode="ok"))

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"]["ok"] is False
    assert "OperationalError" in body["checks"]["database"]["error"]


def test_health_unhealthy_takes_precedence_over_redis_degraded(monkeypatch):
    app.dependency_overrides[get_db] = _override_db("down")
    import app.core.redis_client as redis_module

    monkeypatch.setattr(redis_module, "get_redis", lambda: _FakeRedis(mode="down"))

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
