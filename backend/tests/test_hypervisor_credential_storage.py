"""
US4 — hypervisor credentials are stored encrypted, not in plaintext (T042).

After create_hypervisor() lands, the row in the database has
``password_ciphertext`` populated with Fernet bytes. The legacy plaintext
``password`` column was dropped by migration ``c9e1d4f3b6a2`` — it no
longer exists in the schema or the model. Discovery / connector code reads
the plaintext back through ``hypervisor.password_plain``.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.crud import hypervisor as crud_hypervisor
from app.models.base import Base
from app.models.hypervisor import HypervisorType
from app.services.credentials import get_vault


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


def test_create_stores_ciphertext_only(db_session):
    hv = _create(db_session, password="super-secret!")

    assert hv.password_ciphertext is not None
    assert isinstance(hv.password_ciphertext, (bytes, bytearray))
    assert hv.credential_key_version >= 1

    # The legacy plaintext column no longer exists (dropped by
    # c9e1d4f3b6a2): only password_ciphertext is persisted.
    columns = {c["name"] for c in inspect(db_session.bind).get_columns("hypervisors")}
    assert "password" not in columns, (
        "legacy plaintext column MUST NOT exist after the cutover migration"
    )

    row = db_session.execute(
        text("SELECT password_ciphertext FROM hypervisors WHERE id = :id"),
        {"id": hv.id},
    ).first()
    assert row.password_ciphertext is not None
    assert b"super-secret!" not in bytes(row.password_ciphertext), (
        "ciphertext bytes contain the plaintext substring — not actually encrypted"
    )


def test_password_plain_round_trips_via_the_vault(db_session):
    hv = _create(db_session, password="round-trip-me")

    assert hv.password_plain == "round-trip-me"


def test_update_password_re_encrypts(db_session):
    hv = _create(db_session, password="initial-pass")
    original_ciphertext = bytes(hv.password_ciphertext)

    crud_hypervisor.update_hypervisor(
        db_session,
        hv.id,
        update_data={"password": "rotated-pass"},
    )
    db_session.refresh(hv)

    assert bytes(hv.password_ciphertext) != original_ciphertext, (
        "rotating the password MUST produce fresh ciphertext"
    )
    assert hv.password_plain == "rotated-pass"


def test_row_without_ciphertext_yields_none(db_session):
    # With the legacy plaintext column dropped, a row whose ciphertext is
    # NULL has no credential to recover — password_plain returns None.
    hv = _create(db_session, password="x")
    hv.password_ciphertext = None
    db_session.commit()
    db_session.refresh(hv)

    assert hv.password_plain is None


def test_undecryptable_ciphertext_returns_none(db_session, caplog):
    """Regression: ``password_plain`` MUST return None (not raise, not
    leak) when the ciphertext is present but no key in the rotation set can
    decrypt it. A decrypt failure points at a real key-rotation incident
    the operator must see (silent-failure-hunter P0).
    """
    hv = _create(db_session, password="x")

    # Corrupt the ciphertext: replace with a token encrypted under a key
    # that the live vault never sees. ``MultiFernet.decrypt`` then raises
    # ``InvalidToken`` because no key in the rotation matches.
    foreign_key = Fernet.generate_key()
    foreign_fernet = Fernet(foreign_key)
    hv.password_ciphertext = foreign_fernet.encrypt(b"never-decryptable")
    db_session.commit()
    db_session.refresh(hv)

    # Confirm the live vault genuinely cannot decrypt this token.
    # Narrow to InvalidToken — a bare Exception would let any unrelated
    # bug (settings parse error, AttributeError) pass for "decrypt failed".
    with pytest.raises(InvalidToken):
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
