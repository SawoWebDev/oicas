"""Excel and PDF rendering of a ``ReportResult`` (Task.md §18).

Both formats render exactly the rows/columns of the on-screen report and record a
``report_run`` with the file's SHA-256 so an exported file can be traced to its data versions.
"""
from __future__ import annotations

import hashlib
import io
import re
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from sqlalchemy.orm import Session

from ..models import ReportRun, User
from . import audit
from .reports import REGISTRY, Column, ReportResult

LOGO = Path(__file__).resolve().parents[1] / "web" / "static" / "img" / "sawo-logo.png"
BRAND_RED = "E31E24"
NUM_FMT = {"qty": "#,##0.00###", "int": "#,##0", "pct": "0.00%", "date": "yyyy-mm-dd", "longdate": "mmmm dd, yyyy", "datetime": "yyyy-mm-dd hh:mm"}


def fmt(value, kind: str) -> str:
    """Text formatting shared by the HTML screens and the PDF export."""
    if value is None or value == "":
        return "–"
    if kind == "pct":
        return f"{value * 100:,.2f}%"
    if kind == "qty":
        s = f"{value:,.5f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    if kind == "int":
        return f"{int(value):,}"
    if kind == "date":
        return value.strftime("%Y-%m-%d") if isinstance(value, (date, datetime)) else str(value)
    if kind == "longdate":  # September 01, 2026
        return value.strftime("%B %d, %Y") if isinstance(value, (date, datetime)) else str(value)
    if kind == "datetime":
        return value.astimezone().strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else str(value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _plain(v):
    """Excel cells cannot hold tz-aware datetimes."""
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone().replace(tzinfo=None)
    if isinstance(v, (dict, list)):
        return str(v)
    return v


def _meta_lines(res: ReportResult) -> list[str]:
    m = dict(res.meta)
    out = []
    gen = m.pop("generated_at", None)
    if gen:
        out.append(f"Generated: {fmt(gen, 'datetime')}")
    for label, key in (("Period", "period"), ("Analysis period", "analysis_period"), ("As of", "as_of"),
                       ("Analysis run", "analysis_run_id"), ("Rule set version", "rule_set_version"),
                       ("Odoo snapshot", "latest_odoo_snapshot")):
        if m.get(key) not in (None, ""):
            out.append(f"{label}: {fmt(m[key], 'date') if isinstance(m[key], date) else m[key]}")
    filters = m.get("filters") or {}
    out.append("Filters: " + (", ".join(f"{k}={v}" for k, v in filters.items()) if filters else "none"))
    if m.get("note"):
        out.append(f"Note: {m['note']}")
    return out


def to_xlsx(res: ReportResult) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", "", res.title)[:31] or "Report"
    top = 1
    if LOGO.exists():
        img = XLImage(str(LOGO))
        img.width, img.height = 120, 76
        ws.add_image(img, "A1")
        top = 6
    ws.cell(top, 1, res.title).font = Font(bold=True, size=14, color=BRAND_RED)
    lines = _meta_lines(res)
    for i, line in enumerate(lines, start=top + 1):
        ws.cell(i, 1, line).font = Font(italic=True, color="555555")
    hdr = top + len(lines) + 2
    fill = PatternFill("solid", fgColor="1F1F1F")
    for c, col in enumerate(res.columns, start=1):
        cell = ws.cell(hdr, c, col.label)
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), fill
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    for r, row in enumerate(res.rows, start=hdr + 1):
        for c, col in enumerate(res.columns, start=1):
            cell = ws.cell(r, c, _plain(row.get(col.key)))
            if col.kind in NUM_FMT:
                cell.number_format = NUM_FMT[col.kind]
    totals = res.totals()
    if totals and res.rows:
        tr = hdr + len(res.rows) + 1
        ws.cell(tr, 1, "Total").font = Font(bold=True)
        for c, col in enumerate(res.columns, start=1):
            if col.key in totals:
                cell = ws.cell(tr, c, totals[col.key])
                cell.font, cell.number_format = Font(bold=True), NUM_FMT.get(col.kind, "General")
    for c, col in enumerate(res.columns, start=1):
        longest = max([len(col.label)] + [len(fmt(row.get(col.key), col.kind)) for row in res.rows[:500]])
        ws.column_dimensions[get_column_letter(c)].width = min(max(10, longest + 2), 60)
    ws.freeze_panes = ws.cell(hdr + 1, 2)
    if res.rows:
        ws.auto_filter.ref = f"A{hdr}:{get_column_letter(len(res.columns))}{hdr + len(res.rows)}"
    if res.summary:
        s = wb.create_sheet("Summary")
        s.cell(1, 1, res.title).font = Font(bold=True, size=13)
        for i, (label, value, kind) in enumerate(res.summary, start=3):
            s.cell(i, 1, label)
            cell = s.cell(i, 2, _plain(value))
            if kind in NUM_FMT:
                cell.number_format = NUM_FMT[kind]
        s.column_dimensions["A"].width, s.column_dimensions["B"].width = 40, 18
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(res: ReportResult, landscape_mode: bool = True) -> bytes:
    buf = io.BytesIO()
    size = landscape(A4) if landscape_mode else portrait(A4)
    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=res.title, author="OICAS")
    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=7, leading=8.5)
    head = st["BodyText"].clone("head", fontSize=7, leading=8.5, textColor=colors.white, fontName="Helvetica-Bold")
    story = []
    if LOGO.exists():
        story.append(Image(str(LOGO), width=30 * mm, height=19 * mm, hAlign="LEFT"))
    story.append(Paragraph(res.title, st["Title"].clone("t", alignment=0, textColor=colors.HexColor(f"#{BRAND_RED}"))))
    for line in _meta_lines(res):
        story.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;"), st["BodyText"].clone("m", fontSize=8, leading=10)))
    if res.summary:
        story.append(Paragraph(" · ".join(f"<b>{lbl}</b>: {fmt(v, k)}" for lbl, v, k in res.summary),
                               st["BodyText"].clone("s", fontSize=8, leading=10)))
    story.append(Spacer(1, 4 * mm))
    cols: list[Column] = res.columns
    data = [[Paragraph(c.label, head) for c in cols]]
    for row in res.rows:
        data.append([Paragraph(fmt(row.get(c.key), c.kind).replace("&", "&amp;").replace("<", "&lt;"), small) for c in cols])
    totals = res.totals()
    if totals and res.rows:
        data.append([Paragraph("<b>Total</b>" if i == 0 else (f"<b>{fmt(totals[c.key], c.kind)}</b>" if c.key in totals else ""), small)
                     for i, c in enumerate(cols)])
    avail = size[0] - 20 * mm
    weights = [3.5 if c.key in ("description", "detail", "scope", "error", "last_note") else 1.0 for c in cols]
    widths = [avail * w / sum(weights) for w in weights]
    t = LongTable(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F1F1F")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F6F6")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(t)

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(10 * mm, 7 * mm, f"OICAS · {res.title}")
        canvas.drawRightString(size[0] - 10 * mm, 7 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def export(db: Session, user: User | None, res: ReportResult, fmt_: str, params: dict) -> tuple[bytes, str, str]:
    if fmt_ == "xlsx":
        data, mime = to_xlsx(res), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt_ == "pdf":
        data, mime = to_pdf(res, REGISTRY[res.key].landscape if res.key in REGISTRY else True), "application/pdf"
    else:
        raise ValueError("format must be xlsx or pdf")
    name = f"OICAS_{res.key}_{datetime.now():%Y%m%d_%H%M%S}.{fmt_}"
    digest = hashlib.sha256(data).hexdigest()
    rr = ReportRun(report_key=res.key, fmt=fmt_, params={k: str(v) for k, v in params.items()}, row_count=len(res.rows),
                   snapshot_id=res.meta.get("latest_odoo_snapshot"), analysis_run_id=res.meta.get("analysis_run_id"),
                   rule_set_id=res.meta.get("rule_set_version"), file_name=name, sha256=digest,
                   user_id=user.id if user else None)
    db.add(rr)
    db.flush()
    audit.record(db, user, "report.export", "report_run", rr.id, {"report": res.key, "format": fmt_,
                                                                  "rows": len(res.rows), "sha256": digest})
    return data, mime, name
