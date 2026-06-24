"""
Remediation tests for the auth / users / roles API surface and `deps.py`.

Covers the audit findings remediated in this batch:

- A9   — login user-enumeration: invalid-credentials and inactive-account
         must return an identical 401, with no `X-Account-Status` header.
- A15  — `/auth/change-password` revokes the caller's refresh families.
- A18  — `/auth/logout` only revokes a family the cookie actually owns.
- B10  — `DELETE /users/{id}/roles/{role_id}` rejects removing the last role.
- B13  — `GET /roles` does not leak other tenants' custom roles to a
         non-superuser admin.
- B16  — system-role update/delete returns 403, not 400.
- B17  — `POST /roles/init-system-roles` is gated by `check_permission`.
- B23  — `DELETE /users/{id}` self-deletion guard returns 403, not 400.
- C16  — `get_current_user` returns a generic 401 for a deleted user.
- C20  — no redundant `= None` defaults on `Annotated[..., Depends()]` params.
- S8410 — every `Depends()` in `deps.py` uses `Annotated[Type, Depends(...)]`.

Harness: the in-memory-SQLite + dependency-override recipe from
test_user_admin_rbac.py, plus a fakeredis instance bound into every
get_redis() consumer so the throttle / refresh-family store work without
a live broker.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import auth as auth_module
from app.core import login_throttle
from app.core import redis_client as redis_client_module
from app.core import refresh_token_store
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
)
from app.main import app
from app.models.base import Base
from app.models.role import Role
from app.models.user import User

PASSWORD = "CorrectHorse9!"
PASSWORD_HASH = get_password_hash(PASSWORD)
SUPER_ADMIN_ROLE_NAME = "super_admin"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture
def fake_redis(monkeypatch):
    """In-memory Redis bound into every get_redis() consumer site.

    login_throttle and refresh_token_store each do
    ``from app.core.redis_client import get_redis`` at import time, which
    binds the symbol into their own namespace — so each consumer must be
    patched explicitly, not just the source module.
    """
    server = fakeredis.FakeServer()
    redis = fakeredis.FakeStrictRedis(server=server, decode_responses=True)

    def factory():
        return redis

    monkeypatch.setattr(redis_client_module, "get_redis", factory)
    monkeypatch.setattr(login_throttle, "get_redis", factory)
    monkeypatch.setattr(refresh_token_store, "get_redis", factory)

    yield redis
    redis.flushall()


def _make_role(
    db: Session,
    name: str,
    permissions: dict,
    *,
    is_system_role: bool = False,
) -> Role:
    role = Role(
        name=name,
        description=f"test role {name}",
        permissions=permissions,
        is_system_role=is_system_role,
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
    return _make_role(
        db_session,
        "admin",
        {"users": ["*"], "roles": ["*"], "vms": ["read"]},
    )


@pytest.fixture
def admin(db_session: Session, admin_role: Role) -> User:
    return _make_user(db_session, username="admin", roles=[admin_role])


@pytest.fixture
def superuser(db_session: Session) -> User:
    return _make_user(db_session, username="root", is_superuser=True)


# ---------------------------------------------------------------------------
# A9 — login user-enumeration + timing oracle
# ---------------------------------------------------------------------------


class TestA9LoginEnumeration:

    def test_wrong_password_and_inactive_account_return_identical_401(
        self, fake_redis, client, db_session
    ):
        """An inactive account must be indistinguishable from a wrong
        password — same status, same body, no leaking header."""
        active = _make_user(db_session, username="active")
        inactive = _make_user(db_session, username="inactive", is_active=False)

        wrong_pw = client.post(
            "/api/v1/auth/login",
            json={"email": active.email, "password": "WrongPassword1!"},
        )
        inactive_resp = client.post(
            "/api/v1/auth/login",
            json={"email": inactive.email, "password": PASSWORD},
        )

        assert wrong_pw.status_code == 401
        assert inactive_resp.status_code == 401
        assert wrong_pw.json()["detail"] == inactive_resp.json()["detail"]

    def test_inactive_login_has_no_account_status_header(
        self, fake_redis, client, db_session
    ):
        inactive = _make_user(db_session, username="inactive2", is_active=False)
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": inactive.email, "password": PASSWORD},
        )
        assert resp.status_code == 401
        assert "X-Account-Status" not in resp.headers

    def test_unknown_email_returns_the_same_401(self, fake_redis, client, db_session):
        _make_user(db_session, username="real")
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "Whatever1!"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# A15 — change-password revokes refresh families
# ---------------------------------------------------------------------------


class TestA15ChangePasswordRevokesFamilies:

    def test_change_password_revokes_existing_refresh_families(
        self, fake_redis, client, db_session
    ):
        """After a password change, a refresh token minted before the
        change must no longer work — the family is revoked."""
        user = _make_user(db_session, username="rotator")

        # Mint a refresh token through the real family store.
        family_id, jti = refresh_token_store.create_family(user.id)
        refresh_jwt = create_refresh_token(
            subject=str(user.id), family_id=family_id, jti=jti,
        )
        # Sanity: the family works before the password change.
        assert refresh_token_store.family_user_id(family_id) == user.id

        resp = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "BrandNewPass1!"},
            headers=_auth(user),
        )
        assert resp.status_code == 200

        # The family is gone — the stale refresh token can't be rotated.
        assert refresh_token_store.family_user_id(family_id) is None
        refresh_resp = client.post(
            "/api/v1/auth/refresh",
            cookies={"shiftwise_refresh": refresh_jwt},
        )
        assert refresh_resp.status_code == 401


# ---------------------------------------------------------------------------
# A18 — logout verifies refresh-family ownership
# ---------------------------------------------------------------------------


class TestA18LogoutOwnership:

    def test_logout_does_not_revoke_a_family_the_cookie_does_not_own(
        self, fake_redis, client, db_session
    ):
        """A logout request whose cookie claims user A but carries family B
        (owned by user B) must NOT wipe user B's family."""
        victim = _make_user(db_session, username="victim")
        attacker = _make_user(db_session, username="attacker")

        # Victim's legitimate family.
        victim_family, _ = refresh_token_store.create_family(victim.id)

        # Attacker forges a refresh JWT: sub = attacker, fam = victim's family.
        forged = create_refresh_token(
            subject=str(attacker.id),
            family_id=victim_family,
            jti="forged-jti",
        )

        resp = client.post(
            "/api/v1/auth/logout",
            cookies={"shiftwise_refresh": forged},
        )
        assert resp.status_code == 200
        # Victim's family must survive — the forged cookie did not own it.
        assert refresh_token_store.family_user_id(victim_family) == victim.id

    def test_logout_revokes_a_family_the_cookie_legitimately_owns(
        self, fake_redis, client, db_session
    ):
        """The normal path still works: a cookie that owns its family
        revokes it on logout."""
        user = _make_user(db_session, username="legit")
        family_id, jti = refresh_token_store.create_family(user.id)
        refresh_jwt = create_refresh_token(
            subject=str(user.id), family_id=family_id, jti=jti,
        )

        resp = client.post(
            "/api/v1/auth/logout",
            cookies={"shiftwise_refresh": refresh_jwt},
        )
        assert resp.status_code == 200
        assert refresh_token_store.family_user_id(family_id) is None


# ---------------------------------------------------------------------------
# B10 — last-role guard on role removal
# ---------------------------------------------------------------------------


class TestB10LastRoleGuard:

    def test_removing_the_last_role_is_rejected(
        self, fake_redis, client, db_session, admin
    ):
        viewer = _make_role(db_session, "viewer", {"vms": ["read"]})
        target = _make_user(db_session, username="oneroled", roles=[viewer])

        resp = client.delete(
            f"/api/v1/users/{target.id}/roles/{viewer.id}",
            headers=_auth(admin),
        )
        assert resp.status_code == 400
        db_session.refresh(target)
        assert len(target.roles) == 1  # role still attached

    def test_removing_a_role_when_others_remain_is_allowed(
        self, fake_redis, client, db_session, admin
    ):
        viewer = _make_role(db_session, "viewer2", {"vms": ["read"]})
        editor = _make_role(db_session, "editor2", {"vms": ["read"]})
        target = _make_user(
            db_session, username="tworoled", roles=[viewer, editor]
        )

        resp = client.delete(
            f"/api/v1/users/{target.id}/roles/{viewer.id}",
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        db_session.refresh(target)
        assert len(target.roles) == 1


# ---------------------------------------------------------------------------
# B13 — roles list does not leak custom roles cross-tenant
# ---------------------------------------------------------------------------


class TestB13RolesListTenantScope:

    def test_non_superuser_does_not_see_custom_roles_of_other_tenants(
        self, fake_redis, client, db_session, admin
    ):
        # A system role — global, visible to everyone.
        _make_role(db_session, "viewer", {"vms": ["read"]}, is_system_role=True)
        # A custom role created by some other tenant.
        _make_role(db_session, "secret_custom_role", {"vms": ["read"]})

        resp = client.get("/api/v1/roles", headers=_auth(admin))
        assert resp.status_code == 200
        names = {r["name"] for r in resp.json()}
        assert "secret_custom_role" not in names

    def test_superuser_still_sees_every_role(
        self, fake_redis, client, db_session, superuser
    ):
        _make_role(db_session, "viewer", {"vms": ["read"]}, is_system_role=True)
        _make_role(db_session, "another_custom", {"vms": ["read"]})

        resp = client.get("/api/v1/roles", headers=_auth(superuser))
        assert resp.status_code == 200
        names = {r["name"] for r in resp.json()}
        assert "another_custom" in names


# ---------------------------------------------------------------------------
# B16 — system-role update/delete returns 403
# ---------------------------------------------------------------------------


class TestB16SystemRoleStatus:

    def test_updating_a_system_role_returns_403(
        self, fake_redis, client, db_session, superuser
    ):
        system_role = _make_role(
            db_session, "admin_sys", {"vms": ["read"]}, is_system_role=True
        )
        resp = client.put(
            f"/api/v1/roles/{system_role.id}",
            json={"description": "tampered"},
            headers=_auth(superuser),
        )
        assert resp.status_code == 403

    def test_deleting_a_system_role_returns_403(
        self, fake_redis, client, db_session, superuser
    ):
        system_role = _make_role(
            db_session, "viewer_sys", {"vms": ["read"]}, is_system_role=True
        )
        resp = client.delete(
            f"/api/v1/roles/{system_role.id}",
            headers=_auth(superuser),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# B17 — init-system-roles gated by check_permission
# ---------------------------------------------------------------------------


class TestB17InitSystemRoles:

    def test_admin_with_roles_create_can_init_system_roles(
        self, fake_redis, client, db_session, admin
    ):
        """The admin role grants roles:* — under check_permission it must
        be allowed to call init-system-roles (no superuser flag needed)."""
        resp = client.post(
            "/api/v1/roles/init-system-roles",
            headers=_auth(admin),
        )
        assert resp.status_code == 200

    def test_user_without_roles_create_is_rejected(
        self, fake_redis, client, db_session
    ):
        plain_role = _make_role(db_session, "plain", {"vms": ["read"]})
        plain = _make_user(db_session, username="plainuser", roles=[plain_role])
        resp = client.post(
            "/api/v1/roles/init-system-roles",
            headers=_auth(plain),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# B23 — self-deletion guard returns 403
# ---------------------------------------------------------------------------


class TestB23SelfDeletion:

    def test_self_deletion_returns_403(self, fake_redis, client, db_session):
        deleter_role = _make_role(
            db_session, "deleter", {"users": ["read", "delete"]}
        )
        deleter = _make_user(db_session, username="selfdeleter", roles=[deleter_role])
        resp = client.delete(
            f"/api/v1/users/{deleter.id}",
            headers=_auth(deleter),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# C16 — deleted user → generic 401, not 404
# ---------------------------------------------------------------------------


class TestC16DeletedUser:

    def test_deleted_user_token_returns_401_not_404(
        self, fake_redis, client, db_session
    ):
        """A valid token for a since-deleted user must yield 401 (the token
        is no longer usable) — a 404 would confirm the id never existed and
        leak account-existence information."""
        ghost = _make_user(db_session, username="ghost")
        headers = _auth(ghost)

        db_session.delete(ghost)
        db_session.commit()

        resp = client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# C20 — no redundant `= None` on Annotated Depends params in roles.py
# S8410 — every Depends() in deps.py uses Annotated[Type, Depends(...)]
# ---------------------------------------------------------------------------


def _function_defs(path: Path) -> list[ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
    return out


def _is_depends_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Depends"
    )


class TestC20RolesNoRedundantNoneDefault:

    def test_roles_handlers_have_no_none_default_on_annotated_depends(self):
        """A param typed `Annotated[X, Depends(...)]` must not also carry a
        `= None` default — the default is dead and misleading."""
        roles_path = Path(auth_module.__file__).parent / "roles.py"
        offenders: list[str] = []

        for fn in _function_defs(roles_path):
            args = fn.args
            defaults = args.defaults
            # defaults align to the LAST len(defaults) positional args.
            offset = len(args.args) - len(defaults)
            for i, default in enumerate(defaults):
                arg = args.args[offset + i]
                ann = arg.annotation
                is_annotated = (
                    isinstance(ann, ast.Subscript)
                    and isinstance(ann.value, ast.Name)
                    and ann.value.id == "Annotated"
                )
                if not is_annotated:
                    continue
                # An Annotated[..., Depends()] param with a None literal
                # default is the C20 smell.
                wraps_depends = any(
                    _is_depends_call(sub)
                    for sub in ast.walk(ann)
                )
                if (
                    wraps_depends
                    and isinstance(default, ast.Constant)
                    and default.value is None
                ):
                    offenders.append(f"{fn.name}:{arg.arg}")

        assert offenders == [], f"redundant `= None` defaults: {offenders}"


class TestS8410DepsAnnotated:

    def test_every_depends_in_deps_is_wrapped_in_annotated(self):
        """SonarQube S8410 — `param: T = Depends(...)` is banned; every
        injected dependency must be `param: Annotated[T, Depends(...)]`."""
        from app.api import deps as deps_module

        deps_path = Path(deps_module.__file__)
        offenders: list[str] = []

        for fn in _function_defs(deps_path):
            args = fn.args
            defaults = args.defaults
            offset = len(args.args) - len(defaults)
            for i, default in enumerate(defaults):
                arg = args.args[offset + i]
                if _is_depends_call(default):
                    # A bare `= Depends(...)` default — the violation.
                    offenders.append(f"{fn.name}:{arg.arg}")

        assert offenders == [], f"bare Depends() defaults (S8410): {offenders}"

    def test_deps_module_still_imports_and_callables_resolve(self):
        """The Annotated rewrite must not break importability or the
        public dependency callables."""
        from app.api import deps as deps_module

        assert callable(deps_module.get_current_user)
        assert callable(deps_module.get_current_superuser)
        assert callable(deps_module.get_current_user_tenant)
        assert callable(deps_module.validate_kubevirt_namespace)
        # check_permission is a factory — it must still return a callable.
        assert callable(deps_module.check_permission("vms", "read"))
