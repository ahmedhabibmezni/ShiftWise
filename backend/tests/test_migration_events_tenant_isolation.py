"""
US3 — tenant isolation on the audit endpoint (T015).

Cross-tenant access MUST return ``404 Not Found``, never ``403``, to
avoid leaking the existence of a migration belonging to another tenant
(contracts/migration-events.md § 404). Superusers bypass the guard
because they manage the whole cluster.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.migrations import list_migration_events
from app.crud import migration as crud_migration
from app.models.base import Base
from app.models.migration import MigrationStrategy
from app.models.user import User


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _superuser() -> User:
    return User(
        email="su@example.com",
        username="su",
        hashed_password="x",
        tenant_id="ops",
        is_superuser=True,
    )


def _tenant_user(tenant: str) -> User:
    return User(
        email=f"{tenant}@example.com",
        username=tenant,
        hashed_password="x",
        tenant_id=tenant,
        is_superuser=False,
    )


def _seed_migration(db_session, owner_tenant: str = "t-alpha"):
    return crud_migration.create_migration(
        db_session,
        data={
            "vm_id": 1,
            "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id=owner_tenant,
        target_namespace=f"shiftwise-{owner_tenant}",
    )


def test_cross_tenant_access_returns_404_not_403(db_session):
    """A user from a different tenant MUST see 404, never 403."""
    mig = _seed_migration(db_session, owner_tenant="t-alpha")

    with pytest.raises(HTTPException) as exc:
        list_migration_events(
            mig.id, 200, 0, None, db_session, _tenant_user("t-beta"),
        )
    assert exc.value.status_code == 404, (
        "cross-tenant access leaked existence via a non-404 code "
        f"(got {exc.value.status_code})"
    )


def test_owning_tenant_user_sees_their_audit(db_session):
    mig = _seed_migration(db_session, owner_tenant="t-alpha")

    response = list_migration_events(
        mig.id, 200, 0, None, db_session, _tenant_user("t-alpha"),
    )
    assert len(response.items) >= 1
    assert all(e.tenant_id == "t-alpha" for e in response.items)


def test_superuser_bypasses_tenant_scope(db_session):
    """A superuser MUST see any tenant's audit trail."""
    mig = _seed_migration(db_session, owner_tenant="t-alpha")

    response = list_migration_events(
        mig.id, 200, 0, None, db_session, _superuser(),
    )
    assert len(response.items) >= 1
    assert response.items[0].migration_id == mig.id


def test_nonexistent_migration_id_returns_404_for_everyone(db_session):
    """An unknown migration ID returns 404 regardless of caller role."""
    for caller in (_superuser(), _tenant_user("t-alpha")):
        with pytest.raises(HTTPException) as exc:
            list_migration_events(
                999999, 200, 0, None, db_session, caller,
            )
        assert exc.value.status_code == 404
