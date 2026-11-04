"""Excel export of the Annual Inventory log: one sheet per plant / area / section, in the same look as the other
OICAS exports (logo, dark header, filter buttons, frozen header). Every row of the section is exported, oldest
Entry No. first, whatever search or reconciliation filter is active on screen."""
from __future__ import annotations

import io
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from ..models import User
from . import annual, audit
from .exports import BRAND_RED, LOGO, NUM_FMT, _plain, fmt

LEFT = Alignment(horizontal="left", vertical="center")
HEAD_FILL = PatternFill("solid", fgColor="1F1F1F")
BAND = PatternFill("solid", fgColor="F7F8FA")
THIN = Border(bottom=Side(style="thin", color="E5E7EB"))
# (header, width, number format) in the order of the table on screen
COLUMNS = [("Item code", 20, None), ("Quantity", 14, NUM_FMT["qty"]), ("Location", 26, None), ("Remarks", 34, None),
           ("Reconciliation", 26, None), ("Combined qty", 14, NUM_FMT["qty"]), ("Entry No.", 12, "0"),
           ("Logged by", 22, None), ("Logged at", 18, NUM_FMT["datetime"]),
           ("Last edited by", 22, None), ("Last edited at", 18, NUM_FMT["datetime"])]


def _who(u: User | None) -> str:
    return (u.name or u.login) if u else ""


def _recon_text(rc: dict | None) -> str:
    if not rc:
        return ""
    return f"{'First of' if rc['first'] else 'Entry ' + str(rc['n']) + ' of'} {rc['count']} · total {fmt(rc['total'], 'qty')}"


def _sheet_name(wb: Workbook, p: str, a: str, s: int) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "", f"{p} {annual.AREAS[a]} S{s}")[:31]
    return base if base not in wb.sheetnames else f"{base[:28]}_{len(wb.sheetnames)}"


def _write_section(ws, db: Session, p: str, a: str, s: int, who: str, generated: datetime) -> int:
    rows = annual.entries(db, p, a, s, limit=None)
    rows.sort(key=lambda e: e.entry_no)
    recon = annual.reconcile(rows)
    top = 1
    if LOGO.exists():
        img = XLImage(str(LOGO))
        img.width, img.height = 120, 76
        ws.add_image(img, "A1")
        top = 6
    title = f"Annual Inventory — {annual.PERIOD_LABELS[p]} · {annual.AREAS[a]} · Section {s}"
    ws.cell(top, 1, title).font = Font(bold=True, size=14, color=BRAND_RED)
    for i, line in enumerate((f"Generated: {generated:%Y-%m-%d %H:%M} by {who}", f"Entries: {len(rows)}",
                              "Sorted by Entry No. Reconciliation groups entries that share an item code in this section."), start=top + 1):
        ws.cell(i, 1, line).font = Font(italic=True, color="555555")
    hdr = top + 5
    for c, (label, width, _) in enumerate(COLUMNS, start=1):
        cell = ws.cell(hdr, c, label)
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), HEAD_FILL
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.row_dimensions[hdr].height = 22
    for r, e in enumerate(rows, start=hdr + 1):
        rc = recon.get(e.id)
        values = [e.item_code, e.qty, e.location, e.remarks or "", _recon_text(rc), rc["total"] if rc else None, e.entry_no,
                  _who(e.created_by), _plain(e.created_at), _who(e.updated_by), _plain(e.updated_at)]
        for c, (v, (_, _, nf)) in enumerate(zip(values, COLUMNS), start=1):
            cell = ws.cell(r, c, v)
            cell.alignment, cell.border = LEFT, THIN
            if nf and v is not None:
                cell.number_format = nf
            if (r - hdr) % 2 == 0:
                cell.fill = BAND
    ws.freeze_panes = ws.cell(hdr + 1, 1)
    ws.auto_filter.ref = f"A{hdr}:{get_column_letter(len(COLUMNS))}{max(hdr + len(rows), hdr + 1)}"
    return len(rows)


def to_xlsx(db: Session, user: User, scopes: list[tuple[str, str, int]]) -> tuple[bytes, int]:
    """Workbook with one sheet per (period, area, section); with several scopes a Summary sheet comes first."""
    generated = datetime.now()
    who = _who(user)
    wb = Workbook()
    wb.remove(wb.active)
    summary = wb.create_sheet("Summary") if len(scopes) > 1 else None
    counts: list[tuple[str, str, int, int]] = []
    for p, a, s in scopes:
        ws = wb.create_sheet(_sheet_name(wb, p, a, s))
        counts.append((p, a, s, _write_section(ws, db, p, a, s, who, generated)))
    if summary is not None:
        summary.cell(1, 1, "Annual Inventory — all plants").font = Font(bold=True, size=14, color=BRAND_RED)
        summary.cell(2, 1, f"Generated: {generated:%Y-%m-%d %H:%M} by {who}").font = Font(italic=True, color="555555")
        for c, (label, width) in enumerate((("Plant", 14), ("Area", 14), ("Section", 12), ("Entries", 12), ("Sheet", 22)), start=1):
            cell = summary.cell(4, c, label)
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), HEAD_FILL
            cell.alignment = Alignment(horizontal="left", vertical="center")
            summary.column_dimensions[get_column_letter(c)].width = width
        for r, ((p, a, s, n), name) in enumerate(zip(counts, wb.sheetnames[1:]), start=5):
            for c, v in enumerate((annual.PERIOD_LABELS[p], annual.AREAS[a], f"Section {s}", n), start=1):
                summary.cell(r, c, v).alignment = LEFT
            link = summary.cell(r, 5, name)
            link.hyperlink, link.alignment, link.font = f"#'{name}'!A1", LEFT, Font(color="0563C1", underline="single")
        total = summary.cell(5 + len(counts), 3, "Total")
        total.font, total.alignment = Font(bold=True), LEFT
        t = summary.cell(5 + len(counts), 4, sum(n for *_, n in counts))
        t.font, t.alignment = Font(bold=True), LEFT
        summary.freeze_panes = "A5"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), sum(n for *_, n in counts)


def export(db: Session, user: User, scopes: list[tuple[str, str, int]], label: str, ip: str | None = None) -> tuple[bytes, str]:
    data, rows = to_xlsx(db, user, scopes)
    name = f"OICAS_annual_inventory_{label}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    audit.record(db, user, "annual.export", "annual_inventory_entry", None,
                 {"scope": label, "sheets": len(scopes), "rows": rows}, ip)
    return data, name


def all_scopes() -> list[tuple[str, str, int]]:
    return [(p, a, s) for p in annual.PERIODS for a in annual.AREAS for s in annual.SECTIONS]

