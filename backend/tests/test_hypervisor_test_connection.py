"""
Issue 1 — POST /hypervisors/{id}/test-connection (existing hypervisor).

Probes connectivity using the stored (encrypted) credentials, so an operator
returning days later can re-verify a saved source without re-entering the
password. The handler is called directly with a constructed ``User`` (same
pattern as ``test_infrastructure_api``); ``check_permission`` is out of scope.
The discovery service is faked so no outbound connection is attempted.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import hypervisors as hv_api
from app.models.base import Base
from app.models.hypervisor import Hypervisor, HypervisorStatus, HypervisorType
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
        email="su@example.com", username="su", hashed_password="x",
        tenant_id="ops", is_superuser=True,
    )


def _seed_hypervisor(db) -> Hypervisor:
    h = Hypervisor(
        name="pve-1", tenant_id="ops", type=HypervisorType.PROXMOX,
        host="10.0.0.10", username="root@pam",
        status=HypervisorStatus.UNKNOWN,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


class _FakeService:
    def __init__(self, result):
        self._result = result

    def test_connection(self, hypervisor):
        return self._result


def test_success_marks_active(db_session, monkeypatch):
    h = _seed_hypervisor(db_session)
    monkeypatch.setattr(
        hv_api, "create_discovery_service",
        lambda db: _FakeService({"success": True, "vms_count": 3, "error": None}),
    )

    resp = hv_api.test_existing_hypervisor_connection(h.id, db_session, _superuser())

    assert resp.success is True
    assert resp.vms_count == 3
    db_session.refresh(h)
    assert h.status == HypervisorStatus.ACTIVE
    assert h.last_successful_connection is not None
    assert h.last_error is None


def test_failure_marks_unreachable_and_records_error(db_session, monkeypatch):
    h = _seed_hypervisor(db_session)
    monkeypatch.setattr(
        hv_api, "create_discovery_service",
        lambda db: _FakeService(
            {"success": False, "vms_count": None, "error": "auth failed"},
        ),
    )

    resp = hv_api.test_existing_hypervisor_connection(h.id, db_session, _superuser())

    assert resp.success is False
    assert resp.error == "auth failed"
    db_session.refresh(h)
    assert h.status == HypervisorStatus.UNREACHABLE
    assert h.last_error == "auth failed"


def test_missing_hypervisor_404(db_session, monkeypatch):
    monkeypatch.setattr(
        hv_api, "create_discovery_service",
        lambda db: _FakeService({"success": True, "vms_count": 0, "error": None}),
    )
    with pytest.raises(HTTPException) as exc:
        hv_api.test_existing_hypervisor_connection(9999, db_session, _superuser())
    assert exc.value.status_code == 404
