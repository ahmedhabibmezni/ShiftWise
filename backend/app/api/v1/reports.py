"""
Reports API — synchronous PDF export of the migration stats payload (US5).

The PDF endpoint reuses the existing `/migrations/stats/summary` query
function for its data source, so any future change to the stats shape
is automatically reflected in the PDF without duplicate aggregation
code.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import check_permission
from app.api.v1.migrations import get_migrations_stats
from app.core.database import get_db
from app.models.user import User
from app.services.reports import REPORTS_PDF_ROW_CAP, generate_reports_pdf

logger = logging.getLogger(__name__)
router = APIRouter()

RESOURCE_REPORTS = "reports"


@router.get("/export/pdf")
def export_reports_pdf(
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[
        User,
        Depends(check_permission(RESOURCE_REPORTS, "read")),
    ] = None,
):
    """Render the Reports page payload as a printable PDF.

    RBAC + tenant scoping are delegated to ``get_migrations_stats``
    (which is the canonical source of truth for both shapes). Scopes
    above ``REPORTS_PDF_ROW_CAP`` rows return 413; the operator should
    narrow the scope and retry.

    **Permissions required:** ``reports:read``.
    """
    stats = get_migrations_stats(db, current_user)

    total_rows = (
        1
        + len(stats.by_hypervisor)
        + len(stats.by_tenant)
    )
    if total_rows > REPORTS_PDF_ROW_CAP:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "Scope too large for synchronous export. "
                "Filter by date range."
            ),
        )

    scope_label = "cluster" if current_user.is_superuser else (
        f"tenant-{current_user.tenant_id}"
    )
    generated_at = datetime.now(timezone.utc)
    pdf_bytes = generate_reports_pdf(
        stats,
        scope_label=scope_label,
        generated_at=generated_at,
    )

    filename = (
        f"shiftwise-report-{scope_label}-"
        f"{generated_at.strftime('%Y%m%d')}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
