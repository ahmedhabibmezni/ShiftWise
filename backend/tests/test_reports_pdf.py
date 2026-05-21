"""
US5 — PDF export endpoint (T052).

Exercises the ReportLab-based generator behind GET /reports/export/pdf:
- Returns application/pdf with the documented Content-Disposition shape.
- Embeds the totals visible on the Reports page.
- Includes the per-tenant section only for superusers.
- Rejects oversized scopes with HTTP 413.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import pytest
from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.reports import export_reports_pdf
from app.crud import migration as crud_migration
from app.models.base import Base
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.migration import MigrationStatus, MigrationStrategy
from app.models.user import User
from app.models.virtual_machine import VirtualMachine
from app.schemas.migration import MigrationStats, MigrationStatsByGroup
from app.services.reports import REPORTS_PDF_ROW_CAP, generate_reports_pdf


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


def _seed_one_completed(db_session, tenant: str = "tenant-a"):
    h = Hypervisor(
        name="vsphere-prod",
        type=HypervisorType.VSPHERE,
        host="10.0.0.1",
        port=443,
        username="admin",
        tenant_id=tenant,
    )
    db_session.add(h)
    db_session.commit()
    db_session.refresh(h)
    vm = VirtualMachine(name="vm-1", source_hypervisor_id=h.id, tenant_id=tenant)
    db_session.add(vm)
    db_session.commit()
    db_session.refresh(vm)
    mig = crud_migration.create_migration(
        db_session,
        data={
            "vm_id": vm.id,
            "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id=tenant,
        target_namespace=f"shiftwise-{tenant}",
    )
    crud_migration.set_migration_status(db_session, mig.id, MigrationStatus.COMPLETED)


def _read_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_endpoint_returns_pdf_content_type(db_session):
    _seed_one_completed(db_session)
    response = export_reports_pdf(db_session, _superuser())

    assert response.media_type == "application/pdf"
    assert response.headers["Content-Disposition"].startswith(
        'attachment; filename="shiftwise-report-cluster-'
    )
    assert response.body.startswith(b"%PDF-")


def test_pdf_contains_totals_text_from_stats(db_session):
    _seed_one_completed(db_session)
    response = export_reports_pdf(db_session, _superuser())

    text = _read_pdf_text(response.body)
    assert "Total migrations" in text
    assert "Completed" in text
    assert "Failed" in text


def test_superuser_pdf_includes_by_tenant_section(db_session):
    _seed_one_completed(db_session, tenant="tenant-a")
    response = export_reports_pdf(db_session, _superuser())

    text = _read_pdf_text(response.body)
    assert "By Tenant" in text
    assert "tenant-a" in text


def test_tenant_user_pdf_excludes_by_tenant_section(db_session):
    _seed_one_completed(db_session, tenant="tenant-a")
    response = export_reports_pdf(db_session, _tenant_user("tenant-a"))

    text = _read_pdf_text(response.body)
    assert "By Tenant" not in text


def test_empty_scope_returns_valid_pdf(db_session):
    response = export_reports_pdf(db_session, _superuser())
    text = _read_pdf_text(response.body)
    # Empty per-hypervisor / per-tenant tables show the empty paragraph.
    assert "No data in this scope" in text or "By Hypervisor" in text
    assert response.body.startswith(b"%PDF-")


def test_oversized_scope_returns_413():
    """Unit test against the generator helper, bypassing the DB."""
    huge_stats = MigrationStats(
        total_migrations=99999,
        completed=0,
        failed=0,
        in_progress=0,
        pending=0,
        success_rate=0.0,
        average_duration_seconds=None,
        total_data_transferred_gb=0.0,
        by_tenant=[
            MigrationStatsByGroup(
                key=f"t{i}",
                label=f"t{i}",
                total=1,
                completed=1,
                failed=0,
            )
            for i in range(REPORTS_PDF_ROW_CAP)
        ],
        by_hypervisor=[
            MigrationStatsByGroup(
                key=f"h{i}",
                label=f"h{i}",
                total=1,
                completed=1,
                failed=0,
            )
            for i in range(REPORTS_PDF_ROW_CAP)
        ],
    )
    # Generator itself doesn't enforce the cap — the endpoint does. We
    # exercise the cap via the endpoint with a synthetic stats payload.
    from unittest.mock import patch

    with patch(
        "app.api.v1.reports.get_migrations_stats",
        return_value=huge_stats,
    ):
        with pytest.raises(HTTPException) as exc:
            export_reports_pdf(db=None, current_user=_superuser())

    assert exc.value.status_code == 413
    assert "synchronous" in exc.value.detail.lower()


def test_generator_unit_round_trip():
    """Sanity check on the generator independent of the endpoint."""
    stats = MigrationStats(
        total_migrations=3,
        completed=2,
        failed=1,
        in_progress=0,
        pending=0,
        success_rate=66.7,
        average_duration_seconds=180.0,
        total_data_transferred_gb=120.5,
        by_tenant=[],
        by_hypervisor=[
            MigrationStatsByGroup(
                key="1",
                label="vsphere-prod-1",
                total=3,
                completed=2,
                failed=1,
            )
        ],
    )
    pdf = generate_reports_pdf(
        stats,
        scope_label="tenant-a",
        generated_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )
    assert pdf.startswith(b"%PDF-")
    text = _read_pdf_text(pdf)
    assert "ShiftWise" in text
    assert "vsphere-prod-1" in text
