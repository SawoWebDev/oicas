"""Import Center: Excel imports for data that is not (yet) in Odoo.

Kinds
  items           items not encoded in Odoo (or without a code yet) + OICAS-owned attributes
  book_balances   expected stock for items Odoo doesn't hold; used by reconciliation only when Odoo
                  has no balance for the item (BR-23 fallback, recorded as balance_source = "book")
  count_lines     many count lines at once in the COUNTED LIST layout (sessions are created as
                  *submitted*; a manager finalizes them)

Every import validates the whole file first and is all-or-nothing. ``dry_run`` reports what would
happen without saving. Each real import is audited and recorded in ``sync_run(kind='import')``.
"""
from __future__ import annotations

import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import BinaryIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..engine.reconciliation import PRODUCTION, WAREHOUSE
from ..models import (AnalysisResult, CountEntry, CountPlanItem, CountSession, DemandLine, DqException,
                      InventorySnapshot, Item, ItemFamily, Reconciliation, SnapshotLine, SnapshotQuant, SyncRun,
                      User, utcnow)
from . import audit, counting, dq, rules
from .importers import sha256_of
from .sync import BOOK_SOURCE

NO_CODE_PREFIX = "NC-"
MAX_ROWS = 20000


@dataclass
class ImportResult:
    kind: str
    dry_run: bool
    rows: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


# ------------------------------------------------------------------ templates
TEMPLATES: dict[str, dict] = {
    "items": {
        "title": "Items not in Odoo",
        "columns": ["RM CODE", "DESCRIPTION", "UOM", "MATERIAL SECTION", "ABC FAMILY", "PLANT LOCATION", "REMARK",
                    "TRACKED"],
        "required": ["DESCRIPTION"],
        "help": [
            "One row per item. RM CODE may be left blank if the item has no code yet: OICAS assigns a temporary "
            f"code ({NO_CODE_PREFIX}00001, …). When the item is encoded in Odoo later, use 'Change item code' on the item page.",
            "Existing items are updated (OICAS-owned fields only). For items already in Odoo, description and UoM "
            "stay as in Odoo.",
            "TRACKED: yes/no (default yes) — whether the item is part of the cycle-count masterlist.",
        ],
        "example": ["", "Gasket - silicone 5mm (not yet in Odoo)", "Piece", "Consumables", "Excluded list", "3", "", "yes"],
    },
    "book_balances": {
        "title": "Book balances (items not in Odoo)",
        "columns": ["BALANCE DATE", "RM CODE", "WAREHOUSE", "PRODUCTION", "REMARKS"],
        "required": ["BALANCE DATE", "RM CODE"],
        "help": [
            "The expected (system) quantity for items that Odoo doesn't hold. Reconciliation uses it only when "
            "Odoo has no balance for the item, and only a balance dated on or before the count date.",
            "Leave WAREHOUSE or PRODUCTION blank if unknown (blank ≠ 0). Import the items first.",
        ],
        "example": [date.today().isoformat(), "NC-00001", 120, 0, "from stock card"],
    },
    "count_lines": {
        "title": "Count lines (COUNTED LIST layout)",
        "columns": ["DATE COUNTED", "RM CODE", "COUNTED BY", "COUNT (WH-1)", "COUNT (WH-2)", "COUNT (WH-3)",
                    "COUNT (WH-4)", "COUNT (PROD-1)", "COUNT (PROD-2)", "COUNT (PROD-3)", "COUNT (PROD-4)", "REMARKS",
                    "BOOK WH", "BOOK PROD"],
        "required": ["DATE COUNTED", "RM CODE", "COUNTED BY"],
        "help": [
            "One row per item and count date, like the COUNTED LIST sheet. Blank count cell = not counted; 0 = counted zero.",
            "Rows are grouped into one session per date and counter, created as SUBMITTED; a manager finalizes them.",
            "BOOK WH / BOOK PROD (optional): expected quantity for items not in Odoo, stored as a book balance on that date.",
        ],
        "example": [date.today().isoformat(), "NC-00001", "Christine A", "", "", 118, "", "", "", "", "", "", 120, ""],
    },
    "demand": {
        "title": "Demand / consumption (for AMC and ABC)",
        "columns": ["Components/Created on", "Components/Product/Reference", "Components/Product/Name",
                    "Components/Demand"],
        "required": ["COMPONENTS/CREATED ON", "COMPONENTS/PRODUCT/REFERENCE", "COMPONENTS/DEMAND"],
        "help": [
            "Same columns as the Odoo export used for the legacy Demand sheet: one row per consumption, any date.",
            "Use it for demand that isn't recorded in Odoo (e.g. items not yet encoded). Rows are summed per item and month.",
            "Upload on the AMC Analysis page or here; then calculate a new analysis run that uses this demand batch.",
        ],
        "example": [date.today().isoformat(), "NC-00001", "Gasket - silicone 5mm", 25],
        "example_in_help": True,  # the demand reader takes every row, so keep the example out of DATA
    },
}

ALIASES = {
    "CODE": "RM CODE", "ITEM CODE": "RM CODE", "INTERNAL REFERENCE": "RM CODE", "PRODUCT CODE": "RM CODE",
    "ITEM DESCRIPTION": "DESCRIPTION", "PRODUCT NAME": "DESCRIPTION", "NAME": "DESCRIPTION",
    "UNIT OF MEASURE": "UOM", "U/M": "UOM",
    "DATE": "BALANCE DATE", "DL DATE": "BALANCE DATE",
    "WH": "WAREHOUSE", "ODOO WH": "BOOK WH", "PRE-PROD": "PRODUCTION", "PREPROD": "PRODUCTION",
    "ODOO PRE-PROD": "BOOK PROD", "ODOO PREPROD": "BOOK PROD", "REMARK": "REMARKS",
    "COUNT (PROD- 1)": "COUNT (PROD-1)", "COUNT (PROD- 2)": "COUNT (PROD-2)", "COUNT (PROD- 3)": "COUNT (PROD-3)",
    "COUNT (PROD- 4)": "COUNT (PROD-4)",
}


def template_workbook(kind: str) -> bytes:
    t = TEMPLATES[kind]
    wb = Workbook()
    ws = wb.active
    ws.title = "DATA"
    fill = PatternFill("solid", fgColor="D9EAD3")
    for c, h in enumerate(t["columns"], start=1):
        cell = ws.cell(1, c, h)
        cell.font, cell.fill = Font(bold=True), fill
        cell.alignment = Alignment(wrap_text=True, horizontal="center")
        ws.column_dimensions[cell.column_letter].width = 40 if h == "DESCRIPTION" else 16
    if not t.get("example_in_help"):
        for c, v in enumerate(t["example"], start=1):
            ws.cell(2, c, v).font = Font(italic=True, color="888888")
    ws.freeze_panes = "A2"
    info = wb.create_sheet("HOW TO")
    info["A1"] = f"OICAS import template — {t['title']}"
    info["A1"].font = Font(bold=True, size=13)
    info["A3"] = "Columns: " + " | ".join(t["columns"])
    info["A4"] = "Required: " + ", ".join(c for c in t["columns"] if c.upper() in [r.upper() for r in t["required"]])
    for i, line in enumerate(t["help"], start=6):
        info.cell(i, 1, "• " + line)
    last = len(t["help"]) + 7
    if t.get("example_in_help"):
        info.cell(last, 1, "Example row: " + " | ".join(str(v) for v in t["example"]))
    else:
        info.cell(last, 1, "Row 2 of the DATA sheet is a grey example: it's ignored if left unchanged, or overwrite it.")
    info.cell(last + 1, 1, "Fill the DATA sheet, then upload it in OICAS → Data Import. Use 'Dry run' first to check.")
    info.column_dimensions["A"].width = 140
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ reading
def _norm(h, columns: list[str] | None = None) -> str:
    s = re.sub(r"\s+", " ", str(h or "").replace("\n", " ")).strip().upper()
    if columns and s in columns:
        return s  # exact template column wins over an alias
    return ALIASES.get(s, s)


def _text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def _num(v, label: str, n: int, errors: list[str]) -> float | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        errors.append(f"row {n}: {label} {v!r} is not a number")
        return None


def _date(v, label: str, n: int, errors: list[str]) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v.strip():
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m.%d.%y", "%m.%d.%Y", "%d-%b-%Y", "%d-%b-%y"):
            try:
                return datetime.strptime(v.strip(), fmt).date()
            except ValueError:
                pass
    errors.append(f"row {n}: {label} {v!r} is not a date")
    return None


def read_table(fp: BinaryIO, kind: str) -> tuple[list[tuple[int, dict]], list[str]]:
    """Rows as (excel row number, {COLUMN: value}). The header is the first row (of the first 10)
    that contains all required columns. The template's grey example row is skipped automatically."""
    t = TEMPLATES[kind]
    try:
        wb = load_workbook(fp, data_only=True, read_only=True)
    except Exception as e:  # not an xlsx
        return [], [f"could not read the file as an Excel workbook (.xlsx): {e}"]
    ws = wb["DATA"] if "DATA" in wb.sheetnames else wb.worksheets[0]
    raw = list(ws.iter_rows(values_only=True, max_row=MAX_ROWS + 20))
    wb.close()
    for i, r in enumerate(raw[:10]):
        cols = [_norm(h, t["columns"]) for h in r]
        if all(req in cols for req in t["required"]):
            break
    else:
        return [], [f"no header row with the required columns ({', '.join(t['required'])}) in the first 10 rows"]
    unknown = [c for c in cols if c and c not in t["columns"]]
    rows = []
    example = [_text(v) for v in t["example"]]
    for n, r in enumerate(raw[i + 1:], start=i + 2):
        rec = {c: v for c, v in zip(cols, r) if c in t["columns"]}
        if not any(_text(v) for v in rec.values()):
            continue
        if [_text(rec.get(c)) for c in t["columns"]] == example:
            continue  # untouched example row
        rows.append((n, rec))
    msgs = [] if len(rows) <= MAX_ROWS else [f"too many rows (max {MAX_ROWS})"]
    if unknown:
        msgs.append("WARN:ignored columns not in the template: " + ", ".join(unknown))
    return rows, msgs


def _split(msgs: list[str]) -> tuple[list[str], list[str]]:
    return [m for m in msgs if not m.startswith("WARN:")], [m[5:] for m in msgs if m.startswith("WARN:")]


def _yes(v) -> bool | None:
    s = (_text(v) or "").lower()
    if not s:
        return None
    return s in ("1", "y", "yes", "true", "x")


def _record(db: Session, user: User, kind: str, filename: str, data: bytes, res: ImportResult) -> None:
    run = SyncRun(kind="import", mode="file", triggered_by_id=user.id, status="success", finished_at=utcnow(),
                  scope={"type": kind, "file": filename, "sha256": sha256_of(data)},
                  stats={"rows": res.rows, "created": res.created, "updated": res.updated, "skipped": res.skipped,
                         **{k: v for k, v in res.details.items() if isinstance(v, (int, str))}})
    db.add(run)
    db.flush()
    audit.record(db, user, f"import.{kind}", "sync_run", run.id, run.stats)
    res.details["import_id"] = run.id


# ------------------------------------------------------------------ items
def next_no_code(db: Session, used: set[str]) -> str:
    n = 0
    for c in db.scalars(select(Item.code).where(Item.code.like(f"{NO_CODE_PREFIX}%"))):
        m = re.fullmatch(rf"{re.escape(NO_CODE_PREFIX)}(\d+)", c)
        if m:
            n = max(n, int(m.group(1)))
    for c in used:
        m = re.fullmatch(rf"{re.escape(NO_CODE_PREFIX)}(\d+)", c)
        if m:
            n = max(n, int(m.group(1)))
    return f"{NO_CODE_PREFIX}{n + 1:05d}"


def import_items(db: Session, user: User, fp: BinaryIO, filename: str, dry_run: bool = False) -> ImportResult:
    data = fp.read()
    res = ImportResult("items", dry_run)
    rows, msgs = read_table(io.BytesIO(data), "items")
    res.errors, res.warnings = _split(msgs)
    res.rows = len(rows)
    plants = {str(p) for p in rules.get_setting(db, "plant_locations")}
    families = set(rules.get_setting(db, "abc_families"))
    existing = {i.code: i for i in db.scalars(select(Item))}
    seen: set[str] = set()
    plan = []
    for n, r in rows:
        code = _text(r.get("RM CODE"))
        desc = _text(r.get("DESCRIPTION"))
        if not desc and not (code and code in existing):
            res.errors.append(f"row {n}: DESCRIPTION is required for a new item")
            continue
        if code and len(code) > 120:
            res.errors.append(f"row {n}: RM CODE longer than 120 characters")
            continue
        if code and code in seen:
            res.errors.append(f"row {n}: RM CODE {code} appears twice in the file")
            continue
        plant = _text(r.get("PLANT LOCATION"))
        if plant and plant not in plants:
            res.errors.append(f"row {n}: PLANT LOCATION {plant!r} is not one of {', '.join(sorted(plants))}")
        fam = _text(r.get("ABC FAMILY"))
        if fam and fam not in families:
            res.errors.append(f"row {n}: ABC FAMILY {fam!r} is not one of {', '.join(sorted(families))}")
        if code:
            seen.add(code)
        plan.append((n, code, desc, r, plant, fam))
    if res.errors:
        return res
    for n, code, desc, r, plant, fam in plan:
        if not code:
            code = next_no_code(db, seen)
            seen.add(code)
            res.warnings.append(f"row {n}: no code — assigned temporary code {code}")
        it = existing.get(code)
        vals = {"material_section": _text(r.get("MATERIAL SECTION")), "abc_family": fam, "plant_location": plant,
                "remark": _text(r.get("REMARK"))}
        vals = {k: v for k, v in vals.items() if v is not None}
        tracked = _yes(r.get("TRACKED"))
        if it is None:
            res.created += 1
            if dry_run:
                continue
            it = Item(code=code, description=desc[:500], uom_name=_text(r.get("UOM")), source="import",
                      tracked=True if tracked is None else tracked, created_at=utcnow())
            db.add(it)
            existing[code] = it
            for k, v in vals.items():
                setattr(it, k, v)
            it.is_jit = (vals.get("remark") or "").upper() == "JIT"
        else:
            res.updated += 1
            if it.odoo_product_id and (desc or _text(r.get("UOM"))):
                res.warnings.append(f"row {n}: {code} is in Odoo — description/UoM kept from Odoo")
            if dry_run:
                continue
            if not it.odoo_product_id:
                it.description = (desc or it.description)[:500]
                it.uom_name = _text(r.get("UOM")) or it.uom_name
            for k, v in vals.items():
                setattr(it, k, v)
            if tracked is not None:
                it.tracked = tracked
        if not dry_run and fam and not db.scalars(select(ItemFamily).where(ItemFamily.item_code == code,
                                                                           ItemFamily.family == fam)).first():
            db.add(ItemFamily(item_code=code, family=fam))
    if not dry_run:
        db.flush()
        dq.scan_items(db)
        flag_not_in_odoo(db)
        _record(db, user, "items", filename, data, res)
    return res


def flag_not_in_odoo(db: Session) -> int:
    refs = set(db.scalars(select(Item.code).where(Item.tracked.is_(True), Item.odoo_product_id.is_(None))))
    for c in refs:
        dq.flag(db, "not_in_odoo", c, "Tracked item has no Odoo product (imported or not yet encoded). Counts are "
                "reconciled against imported book balances until it exists in Odoo.", "info", "items")
    dq.auto_resolve(db, "not_in_odoo", refs, "items")
    return len(refs)


# ------------------------------------------------------------------ book balances
def _book_snapshot(db: Session, d: date, label: str, run_ref: str) -> InventorySnapshot:
    tz = ZoneInfo(get_settings().app_timezone)
    snap = InventorySnapshot(taken_at=datetime.combine(d, time(12), tz).astimezone(timezone.utc), source=BOOK_SOURCE,
                             label=label, complete=False)
    db.add(snap)
    db.flush()
    return snap


def import_book_balances(db: Session, user: User, fp: BinaryIO, filename: str, dry_run: bool = False) -> ImportResult:
    data = fp.read()
    res = ImportResult("book_balances", dry_run)
    rows, msgs = read_table(io.BytesIO(data), "book_balances")
    res.errors, res.warnings = _split(msgs)
    res.rows = len(rows)
    items = {i.code: i for i in db.scalars(select(Item))}
    by_date: dict[date, dict[str, tuple]] = defaultdict(dict)
    for n, r in rows:
        d = _date(r.get("BALANCE DATE"), "BALANCE DATE", n, res.errors)
        code = _text(r.get("RM CODE"))
        wh = _num(r.get("WAREHOUSE"), "WAREHOUSE", n, res.errors)
        prod = _num(r.get("PRODUCTION"), "PRODUCTION", n, res.errors)
        if not code:
            res.errors.append(f"row {n}: RM CODE is required")
            continue
        if code not in items:
            res.errors.append(f"row {n}: unknown item {code} — import it in 'Items' first")
            continue
        if d and d > date.today():
            res.errors.append(f"row {n}: BALANCE DATE is in the future")
        if wh is None and prod is None:
            res.errors.append(f"row {n}: enter WAREHOUSE and/or PRODUCTION")
        if d and code in by_date[d]:
            res.errors.append(f"row {n}: {code} appears twice for {d}")
        if items[code].odoo_product_id:
            res.warnings.append(f"row {n}: {code} is in Odoo — its Odoo balance is used; this book balance is kept "
                                "for reference only")
        if d:
            by_date[d][code] = (wh, prod)
    if res.errors:
        return res
    res.created = sum(len(v) for v in by_date.values())
    res.details["dates"] = len(by_date)
    if dry_run:
        return res
    for d, lines in sorted(by_date.items()):
        snap = _book_snapshot(db, d, f"Book balances {d:%Y-%m-%d} ({filename})", filename)
        n = 0
        for code, (wh, prod) in lines.items():
            for bucket, q in ((WAREHOUSE, wh), (PRODUCTION, prod)):
                if q is not None:
                    db.add(SnapshotLine(snapshot_id=snap.id, item_code=code, bucket=bucket, qty=q))
                    n += 1
        snap.line_count = n
    db.flush()
    # refresh reconciliations that had no system balance for these items
    ctx = counting.RecomputeContext(db)
    codes = {c for lines in by_date.values() for c in lines}
    refreshed = 0
    for rc in db.scalars(select(Reconciliation).where(Reconciliation.superseded.is_(False),
                                                      Reconciliation.item_code.in_(codes),
                                                      Reconciliation.status == "odoo_missing")).all():
        counting.recompute(db, rc.item_code, rc.count_date, ctx)
        refreshed += 1
    res.details["reconciliations_refreshed"] = refreshed
    _record(db, user, "book_balances", filename, data, res)
    return res


# ------------------------------------------------------------------ count lines
def import_count_lines(db: Session, user: User, fp: BinaryIO, filename: str, dry_run: bool = False) -> ImportResult:
    data = fp.read()
    res = ImportResult("count_lines", dry_run)
    rows, msgs = read_table(io.BytesIO(data), "count_lines")
    res.errors, res.warnings = _split(msgs)
    res.rows = len(rows)
    known = set(db.scalars(select(Item.code)))
    slots = [(f"COUNT (WH-{k})", WAREHOUSE, str(k)) for k in range(1, 5)] + \
            [(f"COUNT (PROD-{k})", PRODUCTION, str(k)) for k in range(1, 5)]
    groups: dict[tuple[date, str], list] = defaultdict(list)
    books: dict[date, dict[str, tuple]] = defaultdict(dict)
    for n, r in rows:
        d = _date(r.get("DATE COUNTED"), "DATE COUNTED", n, res.errors)
        code, who = _text(r.get("RM CODE")), _text(r.get("COUNTED BY"))
        if not code or not who:
            res.errors.append(f"row {n}: RM CODE and COUNTED BY are required")
            continue
        if code not in known:
            res.errors.append(f"row {n}: unknown item {code} — import it in 'Items' first")
            continue
        if d and d > date.today():
            res.errors.append(f"row {n}: DATE COUNTED is in the future")
        entries = []
        for col, bucket, slot in slots:
            q = _num(r.get(col), col, n, res.errors)
            if q is not None:
                if q < 0:
                    res.errors.append(f"row {n}: negative quantity in {col}")
                entries.append((bucket, slot, q))
        if not entries:
            res.warnings.append(f"row {n}: {code} has no quantity — skipped (blank is not a count)")
            res.skipped += 1
            continue
        bwh = _num(r.get("BOOK WH"), "BOOK WH", n, res.errors)
        bprod = _num(r.get("BOOK PROD"), "BOOK PROD", n, res.errors)
        if d:
            groups[(d, who)].append((code, entries, _text(r.get("REMARKS"))))
            if bwh is not None or bprod is not None:
                books[d][code] = (bwh, bprod)
    if res.errors:
        return res
    res.created = sum(len(e) for g in groups.values() for _, e, _ in g)
    res.details.update(sessions=len(groups), book_balances=sum(len(v) for v in books.values()))
    if dry_run:
        return res
    session_ids = []
    for (d, who), lines in sorted(groups.items()):
        s = CountSession(count_date=d, counted_by_name=who, counter_user_id=None, status="submitted",
                         source="excel_upload", created_by_id=user.id, submitted_at=utcnow(),
                         remarks=f"Imported from {filename}")
        db.add(s)
        db.flush()
        session_ids.append(s.id)
        uoms = dict(db.execute(select(Item.code, Item.uom_name).where(Item.code.in_({c for c, _, _ in lines}))).all())
        for code, entries, remark in lines:
            for bucket, slot, q in entries:
                db.add(CountEntry(session_id=s.id, item_code=code, bucket=bucket, slot=slot, qty=q,
                                  uom_name=uoms.get(code), remarks=remark, created_by_id=user.id))
                remark = None
    for d, lines in books.items():
        snap = _book_snapshot(db, d, f"Book balances from count import {d:%Y-%m-%d} ({filename})", filename)
        for code, (wh, prod) in lines.items():
            for bucket, q in ((WAREHOUSE, wh), (PRODUCTION, prod)):
                if q is not None:
                    db.add(SnapshotLine(snapshot_id=snap.id, item_code=code, bucket=bucket, qty=q))
        snap.line_count = sum((wh is not None) + (prod is not None) for wh, prod in lines.values())
    db.flush()
    res.details["session_ids"] = ", ".join(f"#{i}" for i in session_ids)
    _record(db, user, "count_lines", filename, data, res)
    return res


# ------------------------------------------------------------------ change item code
CODE_TABLES = (CountEntry, Reconciliation, SnapshotLine, SnapshotQuant, DemandLine, AnalysisResult, ItemFamily,
               CountPlanItem)


def rekey_item(db: Session, user: User, old: str, new: str) -> Item:
    """Give an item a new code (e.g. it has now been encoded in Odoo) and move its whole history.

    If Odoo sync already created an item with the new code and it has no counts yet, that item is
    merged in (its Odoo link is kept). Otherwise an existing target code is refused.
    """
    new = (new or "").strip()
    it = db.scalars(select(Item).where(Item.code == old)).first()
    if it is None:
        raise LookupError("item not found")
    if not new or new == old:
        raise ValueError("enter a different new code")
    if len(new) > 120:
        raise ValueError("code too long")
    target = db.scalars(select(Item).where(Item.code == new)).first()
    merged = False
    if target is not None:
        has_history = db.scalar(select(func.count()).select_from(CountEntry).where(CountEntry.item_code == new)) or \
            db.scalar(select(func.count()).select_from(Reconciliation).where(Reconciliation.item_code == new))
        if has_history or it.odoo_product_id:
            raise ValueError(f"code {new} already exists with its own history; can't merge automatically")
        odoo_id, desc, uom, active, synced = (target.odoo_product_id, target.description, target.uom_name,
                                              target.odoo_active, target.last_synced_at)
        db.query(ItemFamily).filter(ItemFamily.item_code == new).delete()
        db.query(SnapshotLine).filter(SnapshotLine.item_code == old,
                                      SnapshotLine.snapshot_id.in_(select(SnapshotLine.snapshot_id)
                                                                   .where(SnapshotLine.item_code == new))).delete(
            synchronize_session=False)
        db.delete(target)
        db.flush()
        it.odoo_product_id, it.description, it.uom_name = odoo_id, desc or it.description, uom or it.uom_name
        it.odoo_active, it.last_synced_at = active, synced
        merged = True
    for model in CODE_TABLES:
        db.execute(update(model).where(model.item_code == old).values(item_code=new))
    db.execute(update(DqException).where(DqException.ref == old).values(ref=new))
    it.code = new
    db.flush()
    flag_not_in_odoo(db)
    audit.record(db, user, "item.rekey", "item", new, {"old_code": old, "new_code": new, "merged_odoo_item": merged})
    return it
