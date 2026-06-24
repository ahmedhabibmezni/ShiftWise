"""
ReportLab PDF generator for the Reports page (US5).

The generator is intentionally synchronous and bounded: scopes above
``REPORTS_PDF_ROW_CAP`` rows are refused by the endpoint with a 413, so
the request returns within a few seconds and the worker never blocks
on a runaway export.

Layout:
- Branded header band — ShiftWise wordmark + report title, with the scope
  and generation timestamp on the right.
- Executive summary — a KPI grid (total / completed / failed / in-progress /
  pending / success rate / average duration / data transferred).
- Per-hypervisor breakdown — always present, scoped by RBAC, with a computed
  success-rate column and a totals row.
- Per-tenant breakdown — only when populated (superuser scope).
- A page footer (page number + confidentiality notice + timestamp) on every
  page via an ``onPage`` canvas callback.

ReportLab is pure-Python, BSD-style licensed, and ships in the existing
OpenShift image without extra system packages — see backend Dockerfile.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
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

# Brand palette — kept local so the report stays self-contained.
_BRAND = colors.HexColor("#E62600")
_BRAND_DARK = colors.HexColor("#0F1535")
_INK = colors.HexColor("#1A1F36")
_MUTED = colors.HexColor("#6B7280")
_HAIRLINE = colors.HexColor("#D8DCE6")
_ZEBRA = colors.HexColor("#F6F7FB")
_CARD_BG = colors.HexColor("#F2F4F9")
_OK = colors.HexColor("#1F9D6A")
_ERR = colors.HexColor("#D93A3A")

_DOC_TITLE = "ShiftWise — Migration Report"


def _fmt_duration(seconds: int | float | None) -> str:
    """Render a second count as a compact ``Hh Mm Ss`` string."""
    if not seconds or seconds <= 0:
        return "—"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _success_pct(completed: int, total: int) -> str:
    if total <= 0:
        return "—"
    return f"{(completed / total) * 100:.0f}%"


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
    timestamp = generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=_DOC_TITLE,
        author="ShiftWise",
    )

    styles = getSampleStyleSheet()
    section_style = ParagraphStyle(
        "ShiftWiseSection",
        parent=styles["Heading2"],
        textColor=_BRAND_DARK,
        fontName="Helvetica-Bold",
        fontSize=13,
        spaceBefore=4,
        spaceAfter=2,
    )
    empty_style = ParagraphStyle(
        "ShiftWiseEmpty",
        parent=styles["Italic"],
        textColor=_MUTED,
        fontSize=10,
        spaceBefore=4,
    )

    flow = [
        _header_band(scope_label, timestamp),
        Spacer(1, 7 * mm),
        _section_heading("Executive Summary", section_style),
        _summary_grid(stats),
        Spacer(1, 7 * mm),
        _section_heading("By Hypervisor", section_style),
        _group_table(stats.by_hypervisor, "Hypervisor", empty_style),
    ]

    if stats.by_tenant:
        flow.extend([
            Spacer(1, 7 * mm),
            _section_heading("By Tenant", section_style),
            _group_table(stats.by_tenant, "Tenant", empty_style),
        ])

    document.build(
        flow,
        onFirstPage=lambda c, d: _draw_footer(c, d, timestamp),
        onLaterPages=lambda c, d: _draw_footer(c, d, timestamp),
    )
    return buffer.getvalue()


def _header_band(scope_label: str, timestamp: str) -> Table:
    """A full-width brand-colored band: wordmark + title on the left, scope
    and generation timestamp on the right."""
    title_style = ParagraphStyle(
        "BandTitle",
        fontName="Helvetica-Bold",
        fontSize=20,
        textColor=colors.white,
        leading=23,
    )
    subtitle_style = ParagraphStyle(
        "BandSubtitle",
        fontName="Helvetica",
        fontSize=9.5,
        textColor=colors.HexColor("#FFD9CC"),
        leading=12,
    )
    meta_style = ParagraphStyle(
        "BandMeta",
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.white,
        alignment=TA_RIGHT,
        leading=13,
    )

    left = [
        Paragraph("ShiftWise", title_style),
        Paragraph("VM Migration Report", subtitle_style),
    ]
    right = Paragraph(
        f"Scope&nbsp;·&nbsp;<b>{scope_label}</b><br/>Generated&nbsp;·&nbsp;{timestamp}",
        meta_style,
    )

    band = Table(
        [[left, right]],
        colWidths=[110 * mm, 68 * mm],
    )
    band.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _BRAND_DARK),
            ("LINEBEFORE", (0, 0), (0, -1), 3, _BRAND),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ])
    )
    return band


def _section_heading(text: str, section_style: ParagraphStyle):
    """A section title followed by a thin brand-colored rule."""
    return Table(
        [
            [Paragraph(text, section_style)],
            [HRFlowable(
                width="100%",
                thickness=1.2,
                color=_BRAND,
                spaceBefore=2,
                spaceAfter=6,
                lineCap="round",
            )],
        ],
        colWidths=["100%"],
        style=TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]),
    )


def _summary_grid(stats: MigrationStats) -> Table:
    """A 4×2 grid of KPI cards covering every figure on the Reports page."""
    cards = [
        ("Total migrations", str(stats.total_migrations), _INK),
        ("Completed", str(stats.completed), _OK),
        ("Failed", str(stats.failed), _ERR),
        ("Success rate", f"{stats.success_rate:.1f}%", _BRAND),
        ("In progress", str(stats.in_progress), _INK),
        ("Pending", str(stats.pending), _INK),
        ("Avg duration", _fmt_duration(stats.average_duration_seconds), _INK),
        ("Data transferred", f"{stats.total_data_transferred_gb:.1f} GB", _INK),
    ]

    label_style = ParagraphStyle(
        "CardLabel",
        fontName="Helvetica",
        fontSize=8,
        textColor=_MUTED,
        alignment=TA_LEFT,
        leading=10,
    )

    def _cell(label: str, value: str, value_color: colors.Color):
        value_style = ParagraphStyle(
            "CardValue",
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=value_color,
            leading=19,
        )
        return [
            Paragraph(label, label_style),
            Spacer(1, 2),
            Paragraph(value, value_style),
        ]

    grid_rows = []
    for i in range(0, len(cards), 4):
        grid_rows.append([_cell(*c) for c in cards[i:i + 4]])

    col = (178 / 4) * mm
    table = Table(grid_rows, colWidths=[col] * 4, hAlign="LEFT")
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _CARD_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, _HAIRLINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    return table


def _group_table(
    rows: list[MigrationStatsByGroup],
    key_label: str,
    empty_style: ParagraphStyle,
):
    if not rows:
        return Paragraph("No data in this scope.", empty_style)

    data = [[key_label, "Total", "Completed", "Failed", "Success"]]
    sum_total = sum_completed = sum_failed = 0
    for row in rows:
        data.append([
            row.label,
            str(row.total),
            str(row.completed),
            str(row.failed),
            _success_pct(row.completed, row.total),
        ])
        sum_total += row.total
        sum_completed += row.completed
        sum_failed += row.failed

    data.append([
        "Total",
        str(sum_total),
        str(sum_completed),
        str(sum_failed),
        _success_pct(sum_completed, sum_total),
    ])

    table = Table(
        data,
        colWidths=[70 * mm, 27 * mm, 27 * mm, 27 * mm, 27 * mm],
        hAlign="LEFT",
        repeatRows=1,
    )

    style = [
        # Header row.
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), _BRAND_DARK),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        # Body.
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), _INK),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _HAIRLINE),
        # Totals row.
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), _CARD_BG),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, _BRAND),
        ("BOX", (0, 0), (-1, -1), 0.5, _HAIRLINE),
    ]
    # Zebra striping on the data rows (exclude header and totals).
    for idx in range(1, len(data) - 1):
        if idx % 2 == 0:
            style.append(("BACKGROUND", (0, idx), (-1, idx), _ZEBRA))

    table.setStyle(TableStyle(style))
    return table


def _draw_footer(canvas, doc, timestamp: str) -> None:
    """Page footer drawn on every page: hairline + confidentiality note,
    timestamp, and page number."""
    canvas.saveState()
    width = doc.pagesize[0]
    y = 12 * mm
    canvas.setStrokeColor(_HAIRLINE)
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, y + 4 * mm, width - doc.rightMargin, y + 4 * mm)

    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(_MUTED)
    canvas.drawString(
        doc.leftMargin, y,
        f"ShiftWise · Confidential · {timestamp}",
    )
    canvas.drawRightString(
        width - doc.rightMargin, y,
        f"Page {doc.page}",
    )
    canvas.restoreState()
