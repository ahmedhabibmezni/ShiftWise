"""
Reports API — synchronous PDF export of the migration stats payload (US5).

The PDF endpoint reuses the existing `/migrations/stats/summary` query
function for its data source, so any future change to the stats shape
is automatically reflected in the PDF without duplicate aggregation
code.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import check_permission
from app.api.v1.migrations import get_migrations_stats
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.services.reports import generate_reports_pdf

logger = logging.getLogger(__name__)
router = APIRouter()

RESOURCE_REPORTS = "reports"

# tenant_id is a free-form String(100); a value with quotes, CR/LF, or
# path separators would corrupt the Content-Disposition header (header
# injection) or write outside the intended path on the client. Restrict
# the slug used inside the download filename to a conservative allowlist.
_SCOPE_LABEL_ALLOWED = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_scope_label(raw: str) -> str:
    """Return a filename-safe version of ``raw`` (alphanumeric + ``.-_``).

    Anything else collapses to a single ``_``. Length-capped at 60 chars
    so an absurdly long tenant_id can't blow out the header. Empty result
    falls back to ``"scope"`` so the filename stays well-formed.
    """
    cleaned = _SCOPE_LABEL_ALLOWED.sub("_", raw).strip("_")[:60]
    return cleaned or "scope"


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
    whose combined breakdown row count exceeds
    ``settings.REPORTS_PDF_MAX_BREAKDOWN_ROWS`` return 413; the operator
    should narrow the scope and retry. The totals header table is fixed
    size and does NOT count against the cap.

    **Permissions required:** ``reports:read``.
    """
    stats = get_migrations_stats(db, current_user)

    breakdown_rows = len(stats.by_hypervisor) + len(stats.by_tenant)
    if breakdown_rows > settings.REPORTS_PDF_MAX_BREAKDOWN_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "Scope too large for synchronous export "
                f"({breakdown_rows} breakdown rows > "
                f"{settings.REPORTS_PDF_MAX_BREAKDOWN_ROWS}). "
                "Contact your administrator to raise "
                "REPORTS_PDF_MAX_BREAKDOWN_ROWS, or split the scope "
                "(e.g. per-tenant export)."
            ),
        )

    raw_scope_label = "cluster" if current_user.is_superuser else (
        f"tenant-{current_user.tenant_id}"
    )
    # Free-form tenant_id never reaches the response header verbatim.
    safe_scope_label = _sanitize_scope_label(raw_scope_label)
    generated_at = datetime.now(timezone.utc)
    pdf_bytes = generate_reports_pdf(
        stats,
        scope_label=raw_scope_label,
        generated_at=generated_at,
    )

    filename = (
        f"shiftwise-report-{safe_scope_label}-"
        f"{generated_at.strftime('%Y%m%d')}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
