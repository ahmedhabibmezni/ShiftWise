"""
Tests pour les endpoints de l'API conversions.

Couvre H-17 : POST /conversions/{uuid}/retry doit ré-enfiler les jobs FAILED
(run_conversion_job.delay) — sinon ils restent bloqués en RETRYING, aucun
worker ne scrutant ce statut.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.conversions import retry_conversion
from app.models.base import Base
from app.models.conversion import (
    ConversionGroup,
    ConversionGroupStatus,
    ConversionJob,
    ConversionStatus,
    ConversionTool,
    SourceFormat,
    TargetFormat,
)
from app.models.user import User
from app.schemas.conversion import ConversionRetry


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_failed_group(db) -> ConversionGroup:
    group = ConversionGroup(
        tenant_id="t1", vm_id=1, migration_id=1,
        group_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        status=ConversionGroupStatus.FAILED,
        target_format=TargetFormat.QCOW2,
    )
    db.add(group)
    db.commit()
    job = ConversionJob(
        tenant_id="t1", group_id=group.id, vm_id=1, disk_index=0,
        source_format=SourceFormat.VMDK, target_format=TargetFormat.QCOW2,
        tool=ConversionTool.QEMU_IMG, status=ConversionStatus.FAILED,
    )
    db.add(job)
    db.commit()
    return group


def test_retry_enqueues_failed_jobs(db_session, monkeypatch):
    group = _seed_failed_group(db_session)
    fake_task = MagicMock()
    monkeypatch.setattr("app.tasks.conversion.run_conversion_job", fake_task)

    superuser = User(
        email="su@example.com", username="su", hashed_password="x",
        tenant_id="t1", is_superuser=True,
    )

    retry_conversion(
        group.group_uuid, ConversionRetry(reset_attempts=False),
        db_session, superuser,
    )

    # H-17: the retried job must actually be handed to a Celery worker.
    assert fake_task.delay.call_count == 1
