"""
Multi-tenancy isolation tests for app/api/v1/users.py.

Ports the unique surface of the legacy ``test_user_management.py`` live-server
script (a ``requests`` + ``psycopg2`` E2E driver, excluded from CI) into a
self-hosted TestClient suite that CI can gate. The legacy script only ran
against a populated Postgres behind a running uvicorn; this suite reproduces
its tenant-isolation assertions with in-memory SQLite + dependency overrides,
no live infrastructure.

Scope — the per-tenant guards on every user-management route:

- ``POST /users``                  non-superuser cannot create outside own tenant
- ``GET  /users``                  non-superuser list is forced to own tenant;
                                   a ``tenant_id`` query param cannot widen it;
                                   superuser sees all tenants and may filter
- ``GET  /users/{id}``             cross-tenant read blocked (403); superuser ok
- ``PUT  /users/{id}``             cross-tenant update blocked (403)
- ``DELETE /users/{id}``           cross-tenant delete blocked (403);
                                   self-deletion blocked (403, Audit B-23)
- ``GET  /users/tenant/{t}/count`` non-superuser cannot count another tenant;
                                   superuser may count any
- ``POST /users/{id}/roles/{r}``   cross-tenant role grant blocked (403)
- ``DELETE /users/{id}/roles/{r}`` last-role removal blocked (400, Audit B-10)

The super-admin protection / privilege-escalation guards live in the sibling
suite ``test_user_admin_rbac.py``; this file deliberately does not duplicate
them — it owns the tenant dimension.

Harness: the in-memory-SQLite + dependency-override recipe shared with
test_user_admin_rbac.py / test_login_audit.py — no live server, Postgres or
Redis required.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.base import Base
from app.models.role import Role
from app.models.user import User

TENANT_ALPHA = "alpha"
TENANT_BETA = "beta"
PASSWORD_HASH = get_password_hash("CorrectHorse9!")
NEW_USER_PASSWORD = "SecurePass9!"


@pytest.fixture
def db_session():
    # StaticPool + check_same_thread=False exposes one in-memory SQLite DB to
    # both the test thread and Starlette's thread-pool worker.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session: Session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def client(db_session: Session):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_role(db: Session, name: str, permissions: dict) -> Role:
    role = Role(
        name=name,
        description=f"test role {name}",
        permissions=permissions,
        is_system_role=False,
        is_active=True,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def _make_user(
    db: Session,
    *,
    username: str,
    tenant_id: str,
    is_superuser: bool = False,
    is_active: bool = True,
    roles: list[Role] | None = None,
) -> User:
    user = User(
        email=f"{username}@example.com",
        username=username,
        hashed_password=PASSWORD_HASH,
        tenant_id=tenant_id,
        is_active=is_active,
        is_verified=True,
        is_superuser=is_superuser,
    )
    if roles:
        user.roles = roles
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(user: User) -> dict:
    """Authorization header carrying a real access token for `user`."""
    return {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}


def _create_payload(username: str, tenant_id: str) -> dict:
    return {
        "email": f"{username}@example.com",
        "username": username,
        "password": NEW_USER_PASSWORD,
        "tenant_id": tenant_id,
    }


@pytest.fixture
def users_admin_role(db_session: Session) -> Role:
    # Full users:* (minus the wildcard) so check_permission always passes —
    # leaving the tenant guard as the rule actually under test, never a
    # missing-permission 403 masquerading as a tenant rejection.
    return _make_role(
        db_session, "tenant_admin", {"users": ["read", "create", "update", "delete"]}
    )


@pytest.fixture
def alpha_admin(db_session: Session, users_admin_role: Role) -> User:
    return _make_user(
        db_session, username="alphaadmin", tenant_id=TENANT_ALPHA, roles=[users_admin_role]
    )


@pytest.fixture
def superuser(db_session: Session) -> User:
    # A superuser bypasses both check_permission and every tenant guard.
    return _make_user(db_session, username="root", tenant_id=TENANT_ALPHA, is_superuser=True)


@pytest.fixture
def beta_user(db_session: Session) -> User:
    return _make_user(db_session, username="betauser", tenant_id=TENANT_BETA)


@pytest.fixture
def alpha_peer(db_session: Session) -> User:
    return _make_user(db_session, username="alphapeer", tenant_id=TENANT_ALPHA)


# ── create ──────────────────────────────────────────────────────────────────


def test_admin_cannot_create_user_in_other_tenant(client, alpha_admin):
    res = client.post(
        "/api/v1/users",
        json=_create_payload("intruder", TENANT_BETA),
        headers=_auth(alpha_admin),
    )
    assert res.status_code == 403


def test_admin_can_create_user_in_own_tenant(client, alpha_admin):
    res = client.post(
        "/api/v1/users",
        json=_create_payload("newalpha", TENANT_ALPHA),
        headers=_auth(alpha_admin),
    )
    assert res.status_code == 201
    assert res.json()["tenant_id"] == TENANT_ALPHA


def test_superuser_can_create_user_in_any_tenant(client, superuser):
    res = client.post(
        "/api/v1/users",
        json=_create_payload("anybeta", TENANT_BETA),
        headers=_auth(superuser),
    )
    assert res.status_code == 201
    assert res.json()["tenant_id"] == TENANT_BETA


# ── list ────────────────────────────────────────────────────────────────────


def test_admin_list_is_scoped_to_own_tenant(client, alpha_admin, alpha_peer, beta_user):
    res = client.get("/api/v1/users", headers=_auth(alpha_admin))
    assert res.status_code == 200
    body = res.json()
    tenants = {u["tenant_id"] for u in body["items"]}
    assert tenants == {TENANT_ALPHA}
    assert all(u["tenant_id"] != TENANT_BETA for u in body["items"])


def test_admin_tenant_filter_param_cannot_widen_scope(
    client, alpha_admin, alpha_peer, beta_user
):
    # Passing ?tenant_id=beta must NOT leak beta users — the filter is forced
    # to the caller's own tenant for non-superusers.
    res = client.get(
        f"/api/v1/users?tenant_id={TENANT_BETA}", headers=_auth(alpha_admin)
    )
    assert res.status_code == 200
    tenants = {u["tenant_id"] for u in res.json()["items"]}
    assert tenants == {TENANT_ALPHA}


def test_superuser_lists_all_tenants(client, superuser, alpha_peer, beta_user):
    res = client.get("/api/v1/users", headers=_auth(superuser))
    assert res.status_code == 200
    tenants = {u["tenant_id"] for u in res.json()["items"]}
    assert TENANT_ALPHA in tenants
    assert TENANT_BETA in tenants


def test_superuser_can_filter_by_tenant(client, superuser, alpha_peer, beta_user):
    res = client.get(
        f"/api/v1/users?tenant_id={TENANT_BETA}", headers=_auth(superuser)
    )
    assert res.status_code == 200
    tenants = {u["tenant_id"] for u in res.json()["items"]}
    assert tenants == {TENANT_BETA}


# ── read ────────────────────────────────────────────────────────────────────


def test_admin_cannot_read_user_in_other_tenant(client, alpha_admin, beta_user):
    res = client.get(f"/api/v1/users/{beta_user.id}", headers=_auth(alpha_admin))
    assert res.status_code == 403


def test_admin_can_read_user_in_own_tenant(client, alpha_admin, alpha_peer):
    res = client.get(f"/api/v1/users/{alpha_peer.id}", headers=_auth(alpha_admin))
    assert res.status_code == 200
    assert res.json()["tenant_id"] == TENANT_ALPHA


def test_superuser_can_read_user_in_any_tenant(client, superuser, beta_user):
    res = client.get(f"/api/v1/users/{beta_user.id}", headers=_auth(superuser))
    assert res.status_code == 200
    assert res.json()["tenant_id"] == TENANT_BETA


# ── update ──────────────────────────────────────────────────────────────────


def test_admin_cannot_update_user_in_other_tenant(client, alpha_admin, beta_user):
    res = client.put(
        f"/api/v1/users/{beta_user.id}",
        json={"first_name": "Tampered"},
        headers=_auth(alpha_admin),
    )
    assert res.status_code == 403


def test_superuser_can_update_user_in_any_tenant(client, superuser, beta_user):
    res = client.put(
        f"/api/v1/users/{beta_user.id}",
        json={"first_name": "Renamed"},
        headers=_auth(superuser),
    )
    assert res.status_code == 200
    assert res.json()["first_name"] == "Renamed"


# ── delete ──────────────────────────────────────────────────────────────────


def test_admin_cannot_delete_user_in_other_tenant(client, alpha_admin, beta_user):
    res = client.delete(f"/api/v1/users/{beta_user.id}", headers=_auth(alpha_admin))
    assert res.status_code == 403


def test_cannot_delete_own_account(client, alpha_admin):
    # Audit B-23: self-deletion is an authorization refusal → 403.
    res = client.delete(f"/api/v1/users/{alpha_admin.id}", headers=_auth(alpha_admin))
    assert res.status_code == 403


def test_admin_can_delete_user_in_own_tenant(client, alpha_admin, alpha_peer):
    res = client.delete(f"/api/v1/users/{alpha_peer.id}", headers=_auth(alpha_admin))
    assert res.status_code == 200
    assert res.json()["success"] is True


# ── tenant count ────────────────────────────────────────────────────────────


def test_admin_cannot_count_other_tenant(client, alpha_admin):
    res = client.get(
        f"/api/v1/users/tenant/{TENANT_BETA}/count", headers=_auth(alpha_admin)
    )
    assert res.status_code == 403


def test_admin_can_count_own_tenant(client, alpha_admin, alpha_peer):
    res = client.get(
        f"/api/v1/users/tenant/{TENANT_ALPHA}/count", headers=_auth(alpha_admin)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["tenant_id"] == TENANT_ALPHA
    # alpha_admin + alpha_peer
    assert body["total_users"] == 2
    assert body["active_users"] == 2
    assert body["inactive_users"] == 0


def test_superuser_can_count_any_tenant(client, superuser, beta_user):
    res = client.get(
        f"/api/v1/users/tenant/{TENANT_BETA}/count", headers=_auth(superuser)
    )
    assert res.status_code == 200
    assert res.json()["tenant_id"] == TENANT_BETA
    assert res.json()["total_users"] == 1


# ── role assignment across tenants ──────────────────────────────────────────


def test_admin_cannot_add_role_to_user_in_other_tenant(
    client, db_session, alpha_admin, beta_user
):
    viewer = _make_role(db_session, "viewer", {"users": ["read"]})
    res = client.post(
        f"/api/v1/users/{beta_user.id}/roles/{viewer.id}",
        headers=_auth(alpha_admin),
    )
    assert res.status_code == 403


def test_cannot_remove_last_role(client, db_session, alpha_admin):
    # Audit B-10: stripping a user's only role would leave it permission-less
    # and unmanageable — rejected with 400.
    viewer = _make_role(db_session, "solo", {"users": ["read"]})
    target = _make_user(
        db_session, username="onlyrole", tenant_id=TENANT_ALPHA, roles=[viewer]
    )
    res = client.delete(
        f"/api/v1/users/{target.id}/roles/{viewer.id}",
        headers=_auth(alpha_admin),
    )
    assert res.status_code == 400
