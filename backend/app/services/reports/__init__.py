"""Reports service package — currently exposes the PDF generator (US5).

Future work (out of bundle): scheduled exports, async PDF generation for
scopes beyond the 1000-row synchronous cap, multi-tenant per-tenant
sub-reports.
"""

from app.services.reports.pdf_export import (
    REPORTS_PDF_ROW_CAP,
    generate_reports_pdf,
)

__all__ = ["generate_reports_pdf", "REPORTS_PDF_ROW_CAP"]
