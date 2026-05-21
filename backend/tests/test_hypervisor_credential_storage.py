"""
US4 — hypervisor credentials are stored encrypted, not in plaintext (T042).

After create_hypervisor() lands, the row in the database has
``password_ciphertext`` populated with Fernet bytes and the legacy
``password`` column is NULL. Discovery / connector code reads the
plaintext back through ``hypervisor.password_plain``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.crud import hypervisor as crud_hypervisor
from app.models.base import Base
from app.models.hypervisor import HypervisorType


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _create(db_session, *, password: str = "super-secret-vsphere-pass"):
    return crud_hypervisor.create_hypervisor(
        db_session,
        data={
            "name": "vsphere-prod-1",
            "type": HypervisorType.VSPHERE,
            "host": "10.0.0.1",
            "port": 443,
            "username": "admin@vsphere.local",
            "password": password,
        },
        tenant_id="tenant-a",
    )


def test_create_stores_ciphertext_and_leaves_legacy_column_null(db_session):
    hv = _create(db_session, password="super-secret!")

    assert hv.password_ciphertext is not None
    assert isinstance(hv.password_ciphertext, (bytes, bytearray))
    assert hv.credential_key_version >= 1

    # Inspect the raw row to confirm the plaintext column is NULL.
    row = db_session.execute(
        text(
            "SELECT password, password_ciphertext "
            "FROM hypervisors WHERE id = :id"
        ),
        {"id": hv.id},
    ).first()
    assert row.password is None, (
        f"legacy plaintext column MUST be NULL for new rows; got {row.password!r}"
    )
    assert row.password_ciphertext is not None
    assert b"super-secret!" not in bytes(row.password_ciphertext), (
        "ciphertext bytes contain the plaintext substring — not actually encrypted"
    )


def test_password_plain_round_trips_via_the_vault(db_session):
    hv = _create(db_session, password="round-trip-me")

    assert hv.password_plain == "round-trip-me"


def test_update_password_re_encrypts_and_clears_legacy_column(db_session):
    hv = _create(db_session, password="initial-pass")

    # Pretend a legacy migration left plaintext lying around.
    hv.password = "legacy-plaintext"
    db_session.commit()

    crud_hypervisor.update_hypervisor(
        db_session,
        hv.id,
        update_data={"password": "rotated-pass"},
    )
    db_session.refresh(hv)

    assert hv.password is None, "legacy column MUST be cleared on update"
    assert hv.password_plain == "rotated-pass"


def test_legacy_row_without_ciphertext_falls_back_to_plaintext(db_session):
    # Simulate a historical row inserted before the vault landed.
    hv = _create(db_session, password="x")
    hv.password_ciphertext = None
    hv.password = "historical-plaintext"
    db_session.commit()
    db_session.refresh(hv)

    assert hv.password_plain == "historical-plaintext"


def test_undecryptable_ciphertext_returns_none_not_legacy_plaintext(
    db_session, caplog
):
    """Regression: ``password_plain`` MUST NOT silently fall back to the
    legacy plaintext column when the ciphertext is present but no key in
    the rotation set can decrypt it. That fallback used to mask key-
    rotation incidents with stale credentials (silent-failure-hunter P0).
    """
    from cryptography.fernet import Fernet

    from app.services.credentials import get_vault

    hv = _create(db_session, password="x")

    # Corrupt the ciphertext: replace with a token encrypted under a key
    # that the live vault never sees. ``MultiFernet.decrypt`` then raises
    # ``InvalidToken`` because no key in the rotation matches.
    foreign_key = Fernet.generate_key()
    foreign_fernet = Fernet(foreign_key)
    hv.password_ciphertext = foreign_fernet.encrypt(b"never-decryptable")
    hv.password = "legacy-stale-plaintext"  # MUST NOT leak through
    db_session.commit()
    db_session.refresh(hv)

    # Confirm the live vault genuinely cannot decrypt this token.
    with pytest.raises(Exception):
        get_vault().decrypt(hv.password_ciphertext)

    import logging
    with caplog.at_level(logging.ERROR, logger="app.models.hypervisor"):
        result = hv.password_plain

    assert result is None, (
        "ciphertext present but undecryptable MUST NOT silently fall back to "
        f"legacy plaintext column; got {result!r}"
    )
    assert any("vault.decrypt failed" in rec.message for rec in caplog.records), (
        "operator MUST see a logger.error message identifying the rotation issue"
    )
