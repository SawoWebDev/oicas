"""Inventory Masterlist page, built the way the INVENTORY MASTERLIST & CYCLE COUNT TRACKER workbook's ``Master``
sheet is built:

* RM code → Plant Location, Interval and Interval (days) come from the latest **AMC Import** upload
  (sheet ``CONSOLIDATED`` of the AMC / ABC Analysis workbook); Description and Unit of Measure come from Odoo.
* Counted Date is the latest ``DATE COUNTED`` of the code in the latest **Physical Counting** upload (sheet
  ``LIST`` of COUNTED LIST.xlsx, Excel ``MAXIFS``); Actual Count (WH) / (PROD) add up columns D / E of the lines
  counted on that date (Excel ``SUMIFS``).
* Next Count = Counted Date + Interval (days); Stock in Months = (Actual WH + Actual PROD) ÷ AMC.
* Odoo WH / Odoo Pre-Prod are the balances of the latest Odoo snapshot; Discrepancy = Actual − Odoo.
* Remark is typed on the page (``masterlist_remark``); until then the item's own remark is shown.

Without an AMC upload the rows fall back to the tracked items and the approved analysis run.
"""
from __future__ import annotations

import io
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine import amc as amc_mod
from ..engine.reconciliation import PRODUCTION, WAREHOUSE
from ..models import AmcImport, Item, MasterlistRemark, User, utcnow
from . import analysis, audit, sync

TOL = 1e-9


@dataclass
class Row:
    code: str
    description: str | None = None
    action: str | None = None
    classification: str | None = None
    amc: float | None = None
    material_section: str | None = None
    plant_location: str | None = None
    interval: str | None = None
    interval_days: int | None = None
    uom: str | None = None
    counted_date: date | None = None
    next_count: date | None = None
    actual_wh: float | None = None
    actual_prod: float | None = None
    stock_in_months: float | None = None
    odoo_wh: float | None = None
    odoo_prod: float | None = None
    disc_wh: float | None = None
    disc_prod: float | None = None
    remark: str | None = None

    @property
    def counted(self) -> bool:
        return self.counted_date is not None

    @property
    def has_discrepancy(self) -> bool:
        return any(d is not None and abs(d) > TOL for d in (self.disc_wh, self.disc_prod))

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Dataset:
    rows: list[Row]
    amc_import: AmcImport | None
    counted_import: AmcImport | None
    snapshot_id: int | None


# ------------------------------------------------------------------ reading the uploaded workbooks
def _key(code) -> str:
    return _text(code).casefold()  # Excel lookups ignore case


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 20000 < v < 80000:
        return date(1899, 12, 30) + timedelta(days=int(v))  # Excel serial day
    s = _text(v)
    for f in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def _norm(h) -> str:
    return " ".join(_text(h).casefold().split())


def _find_header(ws, wanted: str, scan: int = 15) -> tuple[int, list[str]] | None:
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=scan, values_only=True), 1):
        hdr = [_norm(c) for c in row]
        if any(h == wanted for h in hdr):
            return i, hdr
    return None


def _col(hdr: list[str], *names: str, default: int | None = None) -> int | None:
    for n in names:
        for i, h in enumerate(hdr):
            if h == n:
                return i
    for n in names:
        for i, h in enumerate(hdr):
            if h.endswith(n):  # "total: 6268 rm code"
                return i
    return default


def _sheet(wb, preferred: str, needle: str):
    for ws in wb.worksheets:
        if ws.title.strip().casefold() == preferred:
            return ws
    for ws in wb.worksheets:
        if getattr(ws, "sheet_state", "visible") == "visible" and _find_header(ws, needle):
            return ws
    return None


def parse_amc(content: bytes) -> list[dict]:
    """Every ``CONSOLIDATED`` row (a code listed in two families stays twice, as in the tracker): description,
    action, classification, AMC, section, plant, interval, days."""
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = _sheet(wb, "consolidated", "amc")
        if ws is None:
            return []
        found = _find_header(ws, "code") or _find_header(ws, "amc")
        if not found:
            return []
        hr, hdr = found
        c_code = _col(hdr, "code", "rm code", default=1)
        c_desc = _col(hdr, "description")
        c_act, c_cls = _col(hdr, "action"), _col(hdr, "classification")
        c_amc, c_sec, c_plant = _col(hdr, "amc"), _col(hdr, "material section"), _col(hdr, "plant location")
        c_int = _col(hdr, "interval")
        c_days = _col(hdr, "interval (days)", "# days", "interval days")
        if c_int is None and c_plant is not None:
            c_int = c_plant + 1  # unlabelled columns after Plant Location: interval code (ABMTS), days (30)
        if c_days is None and c_int is not None:
            c_days = c_int + 1
        cat, decl = _col(hdr, "category"), _col(hdr, "declared inventory type")

        def at(row, i):
            return row[i] if i is not None and i < len(row) else None

        out: list[dict] = []
        for row in ws.iter_rows(min_row=hr + 1, values_only=True):
            code = _text(at(row, c_code))
            if not code:
                continue
            interval = _text(at(row, c_int)) or (_text(at(row, cat)) + _text(at(row, decl))) or None
            days = _num(at(row, c_days))
            out.append({
                "code": code, "description": _text(at(row, c_desc)) or None, "action": _text(at(row, c_act)) or None,
                "classification": _text(at(row, c_cls)) or None, "amc": _num(at(row, c_amc)),
                "material_section": _text(at(row, c_sec)) or None, "plant_location": _text(at(row, c_plant)) or None,
                "interval": interval if interval and not interval.replace(".", "").isdigit() else None,
                "interval_days": int(days) if days is not None else None})
        return out
    finally:
        wb.close()


def parse_counted(content: bytes) -> dict[str, dict]:
    """``LIST`` rows by code: latest DATE COUNTED and the WH / PROD totals counted on that date."""
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = _sheet(wb, "list", "date counted")
        if ws is None:
            return {}
        found = _find_header(ws, "date counted")
        hr, hdr = found if found else (1, [])
        c_date = _col(hdr, "date counted", default=0)
        c_code = _col(hdr, "rm code", "code", default=1)
        c_wh = _col(hdr, "total count (wh)", default=3)
        c_prod = _col(hdr, "total count (prod)", default=4)
        lines: dict[str, list[tuple[date, float | None, float | None]]] = {}
        for row in ws.iter_rows(min_row=hr + 1, values_only=True):
            if len(row) <= max(c_date, c_code):
                continue
            code, d = _text(row[c_code]), _date(row[c_date])
            if not code or d is None:
                continue
            wh = _num(row[c_wh]) if c_wh < len(row) else None
            prod = _num(row[c_prod]) if c_prod < len(row) else None
            lines.setdefault(_key(code), []).append((d, wh, prod))
        out = {}
        for k, ls in lines.items():
            last = max(d for d, _, _ in ls)
            day = [ln for ln in ls if ln[0] == last]
            out[k] = {"counted_date": last, "actual_wh": sum(wh or 0.0 for _, wh, _ in day),
                      "actual_prod": sum(p or 0.0 for _, _, p in day)}
        return out
    finally:
        wb.close()


_CACHE: dict[tuple[int, str, str], object] = {}
_LOCK = threading.Lock()


def _parsed(db: Session, imp: AmcImport | None, kind: str):
    """Parsed upload, cached per upload (an upload never changes; a new upload has a new id)."""
    if imp is None:
        return [] if kind == "amc" else {}
    key = (imp.id, imp.sha256, kind)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    content = db.scalar(select(AmcImport.content).where(AmcImport.id == imp.id))
    try:
        data = (parse_amc if kind == "amc" else parse_counted)(bytes(content or b""))
    except Exception:  # noqa: BLE001 - a broken upload shows as "no data", never as a crashed page
        data = [] if kind == "amc" else {}
    with _LOCK:
        for k in [k for k in _CACHE if k[2] == kind]:
            del _CACHE[k]
        _CACHE[key] = data
    return data


def latest_upload(db: Session, kind: str) -> AmcImport | None:
    return db.scalars(select(AmcImport).where(AmcImport.kind == kind).order_by(AmcImport.uploaded_at.desc(),
                                                                                AmcImport.id.desc())).first()


# ------------------------------------------------------------------ the dataset
def build(db: Session) -> Dataset:
    amc_imp, cnt_imp = latest_upload(db, "amc"), latest_upload(db, "counted")
    amc_rows, counts = _parsed(db, amc_imp, "amc"), _parsed(db, cnt_imp, "counted")
    items = {_key(it.code): it for it in db.scalars(select(Item))}
    remarks = {_key(r.code): r.remark for r in db.scalars(select(MasterlistRemark))}

    rows: list[Row] = []
    if amc_rows:
        rows = [Row(**a) for a in amc_rows]
    else:  # no AMC upload yet: tracked items with the approved analysis run
        run = analysis.current_run(db)
        res = analysis.primary_results(db, run.id) if run else {}
        for it in sorted((i for i in items.values() if i.tracked), key=lambda i: i.code):
            a = res.get(it.code)
            rows.append(Row(code=it.code, action=a.action if a else None,
                            classification=a.classification if a else None, amc=a.amc if a else None,
                            material_section=it.material_section, plant_location=it.plant_location,
                            interval=(((a.category or "") + (a.declared_type or "")) or None) if a else None,
                            interval_days=a.interval_days if a else None))

    snap = sync.latest_snapshot(db)
    odoo_codes = [items[_key(r.code)].code for r in rows if _key(r.code) in items]
    bal = sync.balances(db, snap, odoo_codes)
    for r in rows:
        k = _key(r.code)
        it = items.get(k)
        if it is not None:
            r.description = it.description or r.description  # Odoo's name wins
            r.uom = it.uom_name
            b = bal.get(it.code) or {}
            r.odoo_wh, r.odoo_prod = b.get(WAREHOUSE), b.get(PRODUCTION)
        c = counts.get(k)
        if c is not None:
            r.counted_date, r.actual_wh, r.actual_prod = c["counted_date"], c["actual_wh"], c["actual_prod"]
            if r.interval_days is not None:
                r.next_count = r.counted_date + timedelta(days=int(r.interval_days))
            r.stock_in_months = amc_mod.stock_in_months(r.actual_wh, r.actual_prod, r.amc)
            if r.odoo_wh is not None:
                r.disc_wh = r.actual_wh - r.odoo_wh
            if r.odoo_prod is not None:
                r.disc_prod = r.actual_prod - r.odoo_prod
        r.remark = remarks[k] if k in remarks else (it.remark if it is not None else None)
    return Dataset(rows, amc_imp, cnt_imp, snap.id if snap else None)


FILTERS = ("q", "classification", "action", "material_section", "plant_location", "counted", "discrepancy")


def apply_filters(rows: list[Row], f: dict) -> list[Row]:
    out = rows
    if f.get("q"):
        needle = f["q"].strip().casefold()
        out = [r for r in out if needle in r.code.casefold() or needle in (r.description or "").casefold()]
    for key in ("classification", "action", "material_section", "plant_location"):
        if f.get(key):
            out = [r for r in out if (getattr(r, key) or "") == f[key]]
    if f.get("counted") in ("yes", "no"):
        want = f["counted"] == "yes"
        out = [r for r in out if r.counted == want]
    if f.get("discrepancy") in ("yes", "no"):
        want = f["discrepancy"] == "yes"
        out = [r for r in out if r.counted and r.has_discrepancy == want]
    return out


def options(db: Session, attr: str) -> list[str]:
    """Distinct values of a column, for the filter drop-downs."""
    amc_rows = _parsed(db, latest_upload(db, "amc"), "amc")
    if amc_rows:
        vals = {a.get(attr) for a in amc_rows}
    else:
        vals = {getattr(it, attr, None) for it in db.scalars(select(Item).where(Item.tracked.is_(True)))}
    return sorted(v for v in vals if v)


# ------------------------------------------------------------------ remarks typed on the page
def set_remark(db: Session, user: User, code: str, remark: str | None) -> str | None:
    code = _text(code)
    if not code:
        raise ValueError("RM code is required")
    remark = (remark or "").strip()[:1000] or None
    rec = db.get(MasterlistRemark, code)
    before = rec.remark if rec else None
    if rec is None:
        rec = MasterlistRemark(code=code)
        db.add(rec)
    rec.remark, rec.updated_by_id, rec.updated_at = remark, user.id, utcnow()
    if before != remark:
        audit.record(db, user, "masterlist.remark", "item", code, {"before": before, "after": remark})
    return remark
