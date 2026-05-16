"""
Unit tests for the user-management RBAC guards in app/api/v1/users.py.

Covers the super-admin protection rules: a non-superuser admin must not
be able to escalate privileges or tamper with a super-admin account.

- update_user / delete_user reject a non-superuser acting on a
  super-admin target — detected via the is_superuser flag OR the
  super_admin role.
- update_user runs the privilege-escalation check on role_ids, closing
  the PUT-bypass hole (only POST /users had the check before).
- a superuser stays unrestricted; an admin keeps full reach over
  ordinary accounts, their own profile, and non-privileged roles.

Also pins the X-Account-Status header on the inactive-account 403 — the
signal the frontend uses to notify a user whose account was just
deactivated.

Harness: the in-memory-SQLite + dependency-override recipe from
test_login_audit.py — no live server, Postgres or Redis required.
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

SUPER_ADMIN_ROLE_NAME = "super_admin"
PASSWORD_HASH = get_password_hash("CorrectHorse9!")


@pytest.fixture
def db_session():
    # StaticPool + check_same_thread=False exposes one in-memory SQLite DB
    # to both the test thread and Starlette's thread-pool worker.
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
    tenant_id: str = "t1",
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


@pytest.fixture
def admin_role(db_session: Session) -> Role:
    return _make_role(db_session, "admin", {"users": ["read", "create", "update"]})


@pytest.fixture
def super_admin_role(db_session: Session) -> Role:
    return _make_role(db_session, SUPER_ADMIN_ROLE_NAME, {"users": ["*"], "roles": ["*"]})


@pytest.fixture
def admin(db_session: Session, admin_role: Role) -> User:
    return _make_user(db_session, username="admin", roles=[admin_role])


@pytest.fixture
def superuser(db_session: Session) -> User:
    return _make_user(db_session, username="root", is_superuser=True)


@pytest.fixture
def regular(db_session: Session) -> User:
    return _make_user(db_session, username="bob")


@pytest.fixture
def super_admin_target(db_session: Session, super_admin_role: Role) -> User:
    # Realistic super-admin: both the flag and the role, same tenant as
    # the admin so the tenant check passes and the super-admin guard is
    # the rule actually under test.
    return _make_user(
        db_session,
        username="owner",
        is_superuser=True,
        roles=[super_admin_role],
    )


def test_admin_cannot_update_a_superuser_account(client, admin, super_admin_target):
    res = client.put(
        f"/api/v1/users/{super_admin_target.id}",
        json={"first_name": "Tampered"},
        headers=_auth(admin),
    )
    assert res.status_code == 403
    assert SUPER_ADMIN_ROLE_NAME in res.json()["detail"]


def test_admin_cannot_update_a_user_holding_the_super_admin_role(
    client, db_session, admin, super_admin_role
):
    # is_superuser is False here — the guard must still fire on the role.
    target = _make_user(
        db_session,
        username="rolesuper",
        is_superuser=False,
        roles=[super_admin_role],
    )
    res = client.put(
        f"/api/v1/users/{target.id}",
        json={"first_name": "Tampered"},
        headers=_auth(admin),
    )
    assert res.status_code == 403
    assert SUPER_ADMIN_ROLE_NAME in res.json()["detail"]


def test_admin_cannot_grant_the_super_admin_role_via_update(
    client, admin, regular, super_admin_role
):
    # The PUT path used to skip _check_privilege_escalation entirely.
    res = client.put(
        f"/api/v1/users/{regular.id}",
        json={"role_ids": [super_admin_role.id]},
        headers=_auth(admin),
    )
    assert res.status_code == 403


def test_admin_can_assign_an_ordinary_role_via_update(client, db_session, admin, regular):
    # Regression: the escalation guard must not block a non-privileged role.
    viewer = _make_role(db_session, "viewer", {"vms": ["read"]})
    res = client.put(
        f"/api/v1/users/{regular.id}",
        json={"role_ids": [viewer.id]},
        headers=_auth(admin),
    )
    assert res.status_code == 200
    assert [r["name"] for r in res.json()["roles"]] == ["viewer"]


def test_admin_can_update_an_ordinary_user(client, admin, regular):
    res = client.put(
        f"/api/v1/users/{regular.id}",
        json={"first_name": "Bob"},
        headers=_auth(admin),
    )
    assert res.status_code == 200
    assert res.json()["first_name"] == "Bob"


def test_admin_can_update_their_own_profile(client, admin):
    res = client.put(
        f"/api/v1/users/{admin.id}",
        json={"first_name": "Selma"},
        headers=_auth(admin),
    )
    assert res.status_code == 200
    assert res.json()["first_name"] == "Selma"


def test_superuser_can_update_a_superuser_account(client, superuser, super_admin_target):
    res = client.put(
        f"/api/v1/users/{super_admin_target.id}",
        json={"first_name": "Renamed"},
        headers=_auth(superuser),
    )
    assert res.status_code == 200
    assert res.json()["first_name"] == "Renamed"


def test_non_superuser_cannot_delete_a_superuser_account(
    client, db_session, super_admin_target
):
    deleter_role = _make_role(
        db_session, "tenant_admin", {"users": ["read", "update", "delete"]}
    )
    deleter = _make_user(db_session, username="deleter", roles=[deleter_role])
    res = client.delete(
        f"/api/v1/users/{super_admin_target.id}",
        headers=_auth(deleter),
    )
    assert res.status_code == 403
    assert SUPER_ADMIN_ROLE_NAME in res.json()["detail"]


def test_inactive_account_403_carries_the_deactivated_header(client, db_session, admin):
    # Token minted while active; the account is deactivated afterwards.
    headers = _auth(admin)
    admin.is_active = False
    db_session.commit()

    res = client.get(f"/api/v1/users/{admin.id}", headers=headers)

    assert res.status_code == 403
    assert res.headers.get("X-Account-Status") == "deactivated"
