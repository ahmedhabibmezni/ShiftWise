"""
ReportLab PDF generator for the Reports page (US5).

The generator is intentionally synchronous and bounded: scopes above
``REPORTS_PDF_ROW_CAP`` rows are refused by the endpoint with a 413, so
the request returns within a few seconds and the worker never blocks
on a runaway export.

Layout:
- Header — ShiftWise wordmark + generation timestamp + scope label.
- Totals — completed / failed / in-progress / pending counts.
- Per-hypervisor breakdown — always present, scoped by RBAC.
- Per-tenant breakdown — only when populated (superuser scope).

ReportLab is pure-Python, BSD-style licensed, and ships in the existing
OpenShift image without extra system packages — see backend Dockerfile.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.config import settings
from app.schemas.migration import MigrationStats, MigrationStatsByGroup


# Backwards-compatible alias for callers and tests that still imported the
# module-level constant. The authoritative source is now
# ``settings.REPORTS_PDF_MAX_BREAKDOWN_ROWS`` — bump it via env / Settings
# instead of editing this file.
REPORTS_PDF_ROW_CAP = settings.REPORTS_PDF_MAX_BREAKDOWN_ROWS


def generate_reports_pdf(
    stats: MigrationStats,
    *,
    scope_label: str,
    generated_at: datetime,
) -> bytes:
    """Render the Reports payload as a printable PDF.

    Returns the raw PDF bytes; the endpoint sets the correct
    ``Content-Type`` / ``Content-Disposition`` headers.
    """
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="ShiftWise — Migration Report",
        author="ShiftWise",
    )

    styles = getSampleStyleSheet()
    header_style = ParagraphStyle(
        "ShiftWiseHeader",
        parent=styles["Title"],
        textColor=colors.HexColor("#E62600"),
        fontSize=22,
        spaceAfter=4,
    )
    subhead_style = ParagraphStyle(
        "ShiftWiseSubhead",
        parent=styles["Normal"],
        textColor=colors.grey,
        fontSize=10,
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "ShiftWiseSection",
        parent=styles["Heading2"],
        textColor=colors.black,
        fontSize=14,
        spaceBefore=10,
        spaceAfter=6,
    )
    empty_style = ParagraphStyle(
        "ShiftWiseEmpty",
        parent=styles["Italic"],
        textColor=colors.grey,
        fontSize=10,
    )

    flow = [
        Paragraph("ShiftWise — Migration Report", header_style),
        Paragraph(
            f"Scope: {scope_label} · Generated: "
            f"{generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            subhead_style,
        ),
        Spacer(1, 4 * mm),
        Paragraph("Totals", section_style),
        _totals_table(stats),
        Spacer(1, 6 * mm),
        Paragraph("By Hypervisor", section_style),
        _group_table(stats.by_hypervisor, "Hypervisor", empty_style),
    ]

    if stats.by_tenant:
        flow.extend([
            Spacer(1, 6 * mm),
            Paragraph("By Tenant", section_style),
            _group_table(stats.by_tenant, "Tenant", empty_style),
        ])

    document.build(flow)
    return buffer.getvalue()


def _totals_table(stats: MigrationStats) -> Table:
    rows = [
        ["Metric", "Value"],
        ["Total migrations", str(stats.total_migrations)],
        ["Completed", str(stats.completed)],
        ["Failed", str(stats.failed)],
        ["In progress", str(stats.in_progress)],
        ["Pending", str(stats.pending)],
        ["Success rate", f"{stats.success_rate:.1f}%"],
        [
            "Data transferred",
            f"{stats.total_data_transferred_gb:.1f} GB",
        ],
    ]
    table = Table(rows, colWidths=[70 * mm, 50 * mm], hAlign="LEFT")
    table.setStyle(_GROUP_TABLE_STYLE)
    return table


def _group_table(
    rows: list[MigrationStatsByGroup],
    key_label: str,
    empty_style: ParagraphStyle,
):
    if not rows:
        return Paragraph("No data in this scope.", empty_style)

    data = [[key_label, "Total", "Completed", "Failed"]]
    for row in rows:
        data.append([
            row.label,
            str(row.total),
            str(row.completed),
            str(row.failed),
        ])
    table = Table(
        data,
        colWidths=[60 * mm, 30 * mm, 30 * mm, 30 * mm],
        hAlign="LEFT",
    )
    table.setStyle(_GROUP_TABLE_STYLE)
    return table


_GROUP_TABLE_STYLE = TableStyle(
    [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
    ]
)
