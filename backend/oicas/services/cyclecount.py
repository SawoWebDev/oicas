"""Cycle Count Planning. Every month is its own saved copy: "Import Inventory Masterlist" copies, into the month
being viewed, every Inventory Masterlist code that has a Next Count today (whatever its date). What is saved in one
month never changes another month, so the same code can sit on different dates in different months.
A manager can then move a code (Adjusted Date) and name who is in charge; the last edit is kept per row."""
from __future__ import annotations

import calendar
import csv
import io
import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CycleCountEntry, User, utcnow
from . import audit, masterlist


@dataclass
class Entry:
    code: str
    description: str | None
    classification: str | None
    plant_location: str | None
    original_date: date
    adjusted_date: date | None
    in_charge: str | None
    last_edit: str | None = None

    @property
    def date(self) -> date:
        return self.adjusted_date or self.original_date

    def as_dict(self) -> dict:
        return {"code": self.code, "original_date": self.original_date, "adjusted_date": self.adjusted_date,
                "description": self.description, "classification": self.classification,
                "plant_location": self.plant_location, "in_charge": self.in_charge, "last_edit": self.last_edit}


def _entry(r: CycleCountEntry) -> Entry:
    return Entry(r.code, r.description, r.classification, r.plant_location, r.original_date, r.adjusted_date,
                 r.in_charge, r.last_edit)


def month_key(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def entries(db: Session, month: str) -> list[Entry]:
    rows = db.scalars(select(CycleCountEntry).where(CycleCountEntry.month == month)).all()
    out = [_entry(r) for r in rows]
    out.sort(key=lambda e: (e.date, e.code.casefold()))
    return out


def last_import(db: Session, month: str):
    return db.scalar(select(CycleCountEntry.imported_at).where(CycleCountEntry.month == month)
                     .order_by(CycleCountEntry.imported_at.desc()).limit(1))


def import_masterlist(db: Session, user: User, month: str) -> dict:
    """Pull the Inventory Masterlist as it is now into ``month``. Codes already in the month keep the Adjusted Date
    and In Charge typed there; codes that left the masterlist are removed unless someone edited them."""
    existing = {r.code.casefold(): r for r in db.scalars(select(CycleCountEntry).where(CycleCountEntry.month == month))}
    seen, added, updated = set(), 0, 0
    now = utcnow()
    for r in masterlist.build(db).rows:
        k = r.code.casefold()
        if r.next_count is None or k in seen:
            continue
        seen.add(k)
        rec = existing.get(k)
        if rec is None:
            db.add(CycleCountEntry(month=month, code=r.code, description=r.description, classification=r.classification,
                                   plant_location=r.plant_location, original_date=r.next_count, imported_at=now,
                                   updated_by_id=user.id))
            added += 1
            continue
        new = (r.description, r.classification, r.plant_location, r.next_count)
        if new != (rec.description, rec.classification, rec.plant_location, rec.original_date):
            rec.description, rec.classification, rec.plant_location, rec.original_date = new
            updated += 1
        rec.imported_at = now
    removed = 0
    for k, rec in existing.items():
        if k not in seen and not rec.last_edit:
            db.delete(rec)
            removed += 1
    audit.record(db, user, "cyclecount.import", "cycle_count", month,
                 {"added": added, "updated": updated, "removed": removed})
    return {"added": added, "updated": updated, "removed": removed, "total": len(seen)}


# ------------------------------------------------------------------ schedule file (the SCHEDULE sheet)
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_CLASSES = ("fast moving", "medium moving", "slow moving", "non moving")


def _schedule_date(v, anchor: date) -> date | None:
    """A cell like ``Oct - 01 - Thu`` has no year: take the year that puts it closest to the month being planned."""
    if isinstance(v, date):
        return v.date() if hasattr(v, "date") else v
    m = re.match(r"\s*([A-Za-z]{3})[A-Za-z]*\s*-\s*(\d{1,2})\b", str(v or ""))
    if not m or m.group(1).lower() not in _MONTHS:
        return masterlist._date(v) if v not in (None, "") else None
    mon, day = _MONTHS[m.group(1).lower()], int(m.group(2))
    best = None
    for y in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            d = date(y, mon, day)
        except ValueError:
            continue
        if best is None or abs((d - anchor).days) < abs((best - anchor).days):
            best = d
    return best


def _grid(content: bytes, filename: str) -> list[list]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            ws = next((w for w in wb.worksheets if w.title.strip().casefold() == "schedule"), None)
            if ws is None:
                ws = next((w for w in wb.worksheets if getattr(w, "sheet_state", "visible") == "visible"
                           and masterlist._find_header(w, "rm code")), None)
            if ws is None:
                raise ValueError("No SCHEDULE sheet found in the workbook")
            return [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return list(csv.reader(io.StringIO(content.decode(enc))))
        except UnicodeDecodeError:
            continue
    raise ValueError("The file could not be read as text")


def parse_schedule(content: bytes, filename: str, anchor: date) -> dict:
    """Rows of the SCHEDULE sheet: RM CODE, DESCRIPTION and CALENDAR (= DATE INPUT + # days). A code listed twice
    keeps its latest CALENDAR date."""
    grid = _grid(content, filename)
    hdr_i = hdr = None
    for i, row in enumerate(grid[:15]):
        h = [masterlist._norm(c) for c in row]
        if "rm code" in h and "calendar" in h:
            hdr_i, hdr = i, h
            break
    if hdr is None:
        raise ValueError("Could not find the RM CODE and CALENDAR columns. Upload the SCHEDULE sheet.")
    c_code, c_cal = hdr.index("rm code"), hdr.index("calendar")
    c_desc = hdr.index("description") if "description" in hdr else None
    c_in = hdr.index("date input") if "date input" in hdr else None
    c_days = next((i for i, x in enumerate(hdr) if x in ("# days", "days")), None)
    best: dict[str, dict] = {}
    skipped = dupes = 0
    for row in grid[hdr_i + 1:]:
        def at(i, row=row):
            return row[i] if i is not None and i < len(row) else None
        code = masterlist._text(at(c_code))
        if not code:
            continue
        d = _schedule_date(at(c_cal), anchor)
        if d is None and c_in is not None and c_days is not None:  # CALENDAR blank: DATE INPUT + # days
            base, n = _schedule_date(at(c_in), anchor), masterlist._num(at(c_days))
            d = base + timedelta(days=int(n)) if base and n is not None else None
        if d is None:
            skipped += 1
            continue
        cls = next((str(c).strip() for c in row if str(c or "").strip().casefold() in _CLASSES), None)
        rec = {"code": code, "description": masterlist._text(at(c_desc)) or None, "classification": cls, "date": d}
        k = code.casefold()
        if k in best:
            dupes += 1
            if d <= best[k]["date"]:
                continue
        best[k] = rec
    return {"rows": list(best.values()), "skipped": skipped, "duplicates": dupes}


def import_schedule(db: Session, user: User, month: str, rows: list[dict]) -> dict:
    """Make ``month`` the schedule file: every code in it on its CALENDAR date. Description, classification and plant
    come from the Inventory Masterlist when the code is there. Rows edited here keep their Adjusted Date and In
    Charge; other rows that are not in the file are removed."""
    ml = {r.code.casefold(): r for r in masterlist.build(db).rows}
    existing = {r.code.casefold(): r for r in db.scalars(select(CycleCountEntry).where(CycleCountEntry.month == month))}
    seen, added, updated, unknown = set(), 0, 0, 0
    now = utcnow()
    for r in rows:
        k = r["code"].casefold()
        seen.add(k)
        m = ml.get(k)
        if m is None:
            unknown += 1
        vals = (m.description if m and m.description else r["description"],
                m.classification if m and m.classification else r["classification"],
                m.plant_location if m else None, r["date"])
        rec = existing.get(k)
        if rec is None:
            db.add(CycleCountEntry(month=month, code=m.code if m else r["code"], description=vals[0],
                                   classification=vals[1], plant_location=vals[2], original_date=vals[3],
                                   imported_at=now, updated_by_id=user.id))
            added += 1
        else:
            if vals != (rec.description, rec.classification, rec.plant_location, rec.original_date):
                rec.description, rec.classification, rec.plant_location, rec.original_date = vals
                updated += 1
            rec.imported_at = now
    removed = 0
    for k, rec in existing.items():
        if k not in seen and not rec.last_edit:
            db.delete(rec)
            removed += 1
    audit.record(db, user, "cyclecount.import_schedule", "cycle_count", month,
                 {"added": added, "updated": updated, "removed": removed, "not_in_masterlist": unknown})
    return {"added": added, "updated": updated, "removed": removed, "total": len(seen), "not_in_masterlist": unknown}


def find(db: Session, month: str, code: str) -> Entry | None:
    rec = _rec(db, month, code)
    return _entry(rec) if rec else None


def _rec(db: Session, month: str, code: str) -> CycleCountEntry | None:
    code = (code or "").strip()
    if not code:
        return None
    return db.scalars(select(CycleCountEntry).where(CycleCountEntry.month == month,
                                                    CycleCountEntry.code.ilike(code.replace("\\", "\\\\")
                                                                               .replace("%", r"\%").replace("_", r"\_"),
                                                                               escape="\\"))).first()


def _d(v: date | None) -> str:
    return v.strftime("%b %d, %Y") if v else "–"


def set_adjustment(db: Session, user: User, month: str, code: str, adjusted_date: date | None = ...,
                   in_charge: str | None = ...) -> Entry:
    """Save Adjusted Date and/or In Charge of one row (omit an argument to leave it; ``None`` clears it). The
    "last edit" note is only rewritten when something really changed."""
    rec = _rec(db, month, code)
    if rec is None:
        raise ValueError(f"{(code or '').strip() or 'Code'} is not in the {month} list. Import the Inventory Masterlist first")
    before = {"adjusted_date": rec.adjusted_date, "in_charge": rec.in_charge}
    if adjusted_date is not ...:
        rec.adjusted_date = None if adjusted_date == rec.original_date else adjusted_date
    if in_charge is not ...:
        rec.in_charge = (in_charge or "").strip()[:120] or None
    after = {"adjusted_date": rec.adjusted_date, "in_charge": rec.in_charge}
    if before != after:
        parts = []
        if before["adjusted_date"] != after["adjusted_date"]:
            parts.append(f"Adjusted Date {_d(before['adjusted_date'] or rec.original_date)} → "
                         f"{_d(after['adjusted_date'] or rec.original_date)}")
        if before["in_charge"] != after["in_charge"]:
            parts.append(f"In Charge {before['in_charge'] or '–'} → {after['in_charge'] or '–'}")
        stamp = utcnow().astimezone().strftime("%b %d, %Y %H:%M")
        rec.last_edit = f"{'; '.join(parts)} · {user.name or user.login} · {stamp}"[:300]
        rec.updated_by_id, rec.updated_at = user.id, utcnow()
        audit.record(db, user, "cyclecount.adjust", "item", rec.code,
                     {"month": month, "before": before, "after": after})
    return _entry(rec)


def parse_month(v: str | None, default: date) -> tuple[int, int]:
    try:
        y, m = (int(x) for x in (v or "").split("-"))
        if 1 <= m <= 12 and 1900 <= y <= 9999:
            return y, m
    except ValueError:
        pass
    return default.year, default.month


def shift(y: int, m: int, delta: int) -> tuple[int, int]:
    i = y * 12 + (m - 1) + delta
    return i // 12, i % 12 + 1


def month_weeks(y: int, m: int) -> list[list[date]]:
    """Weeks (Sunday first) covering the month, including the neighbouring days that fill the first/last week."""
    return [list(wk) for wk in calendar.Calendar(firstweekday=6).monthdatescalendar(y, m)]
