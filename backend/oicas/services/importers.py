"""Excel importers.

1. Legacy migration (one-off): the three operational workbooks → items, families, demand batch,
   legacy analysis run, Odoo download snapshots, count sessions/entries, reconciliations.
2. Recurring uploads: filled count sheets (same layout as the e-mailed form), demand exports
   (raw Odoo "Components" export or the legacy Demand pivot), item attribute lists.

Imports are recorded as ``sync_run(kind='import')`` with the file SHA-256; re-importing the same
file is refused so history is never duplicated.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import BinaryIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..engine import classification
from ..engine.amc import Period, add_months
from ..engine.reconciliation import PRODUCTION, WAREHOUSE
from ..models import (AnalysisResult, AnalysisRun, CountEntry, CountSession, DemandBatch, DemandLine,
                      InventorySnapshot, Item, ItemFamily, Reconciliation, SnapshotLine, SyncRun, User, utcnow)
from . import audit, counting, dq, rules

SHEET_FAMILY = {"RM": "RAW MAT", "Box ABC Analysis": "BOX", "MS ABC Analysis": "Metal Stamping",
                "PA ABC Analysis": "Pre-Assy", "Stone ABC Analysis": "Stone", "T&D ABC Analysis": "T&D",
                "PIM ABC Analysis": "PIM", "CU ABC Analysis": "Control Unit", "WS ABC Analysis": "Wood",
                "List excluded": "Excluded list", "SF Wood ABC Analysis": "SF Wood"}
LEGACY_ABC_START = date(2025, 9, 1)  # family sheet column D = Sep (2025)
LEGACY_ABC_MONTHS = 11  # frequency divisor in the workbook (F-09)
LEGACY_DEMAND_FIRST_MONTH = date(2025, 8, 1)  # Demand sheet column C = Aug (2025)


class ImportError_(ValueError):
    pass


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _text(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m.%d.%y", "%m.%d.%Y"):
            try:
                return datetime.strptime(v.strip(), fmt).date()
            except ValueError:
                pass
    return None


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _begin_import(db: Session, user: User | None, kind: str, name: str, digest: str, force: bool) -> SyncRun:
    if not force:
        prev = db.scalars(select(SyncRun).where(SyncRun.kind == "import", SyncRun.status == "success")).all()
        for p in prev:
            if p.scope.get("sha256") == digest and p.scope.get("type") == kind:
                raise ImportError_(f"this file was already imported (import #{p.id} on {p.started_at:%Y-%m-%d}); "
                                   "importing it again would duplicate history")
    run = SyncRun(kind="import", mode="file", triggered_by_id=user.id if user else None,
                  scope={"type": kind, "file": name, "sha256": digest})
    db.add(run)
    db.flush()
    return run


def _finish(db: Session, user: User | None, run: SyncRun, stats: dict) -> SyncRun:
    run.status, run.stats, run.finished_at = "success", stats, utcnow()
    audit.record(db, user, f"import.{run.scope['type']}", "sync_run", run.id, stats)
    return run


class _Items:
    """Item lookup with Excel-style case-insensitive fallback (legacy XLOOKUP/MAXIFS semantics)."""

    def __init__(self, db: Session):
        self.db = db
        self.by_code = {i.code: i for i in db.scalars(select(Item))}
        self.by_fold: dict[str, list[Item]] = defaultdict(list)
        for i in self.by_code.values():
            self.by_fold[i.code.casefold()].append(i)

    def get(self, code: str) -> Item | None:
        it = self.by_code.get(code)
        if it is None:
            cands = self.by_fold.get(code.casefold(), [])
            if len(cands) == 1:
                dq.flag(self.db, "unknown_item_code", code, f"matched case-insensitively to {cands[0].code}", "info",
                        "import")
                return cands[0]
        return it

    def create(self, code: str, **kw) -> Item:
        it = Item(code=code, **kw)
        self.db.add(it)
        self.by_code[code] = it
        self.by_fold[code.casefold()].append(it)
        return it


# ------------------------------------------------------------------ legacy: AMC / ABC workbook
def import_amc_workbook(db: Session, user: User | None, path: Path, force: bool = False,
                        approve_legacy_run: bool = True) -> SyncRun:
    data = path.read_bytes()
    run = _begin_import(db, user, "legacy_amc", path.name, sha256_of(data), force)
    wb = load_workbook(path, data_only=True, read_only=True)
    items = _Items(db)
    stats: dict = {"families": {}, "items_created": 0}

    # Demand sheet → demand batch (numeric cells only; "" = missing)
    ws = wb["Demand"]
    batch = DemandBatch(source="excel", label=f"Legacy Demand sheet ({path.name})", period_start=LEGACY_DEMAND_FIRST_MONTH,
                        period_end=add_months(LEGACY_DEMAND_FIRST_MONTH, 11), file_sha256=sha256_of(data),
                        sync_run_id=run.id, created_by_id=user.id if user else None)
    db.add(batch)
    db.flush()
    lines = {}
    for row in ws.iter_rows(min_row=3, max_col=14, values_only=True):
        code = _text(row[0])
        if not code:
            continue
        for i, v in enumerate(row[2:14]):
            q = _num(v)
            if q is not None:
                lines[(code, add_months(LEGACY_DEMAND_FIRST_MONTH, i))] = q
    db.add_all([DemandLine(batch_id=batch.id, item_code=c, month=m, qty=q) for (c, m), q in lines.items()])
    batch.line_count = len(lines)
    stats["demand_lines"] = len(lines)

    # Family sheets → items, memberships, legacy analysis results (cached workbook values)
    rs = rules.ensure_default_rule_set(db)
    arun = AnalysisRun(source="legacy_import", period_start=LEGACY_ABC_START, months=LEGACY_ABC_MONTHS,
                       demand_batch_id=batch.id, rule_set_id=rs.id, status="draft",
                       notes=f"Cached values imported from {path.name} family sheets (legacy official results)",
                       created_by_id=user.id if user else None)
    db.add(arun)
    db.flush()
    existing_fam = {(f.item_code, f.family) for f in db.scalars(select(ItemFamily))}
    results = []
    for sheet, family in SHEET_FAMILY.items():
        n = 0
        for r in wb[sheet].iter_rows(min_row=3, max_col=30, values_only=True):
            code = _text(r[1])
            if not code:
                continue
            n += 1
            it = items.by_code.get(code)
            if it is None:
                it = items.create(code, description=_text(r[2]) or "", source="legacy", tracked=False)
                stats["items_created"] += 1
            if it.abc_family is None:
                it.abc_family = family
            sec, plant = _text(r[28]), _text(r[29])
            if it.material_section is None and sec not in (None, "0"):
                it.material_section = sec
            if it.plant_location is None and plant not in (None, "0"):
                it.plant_location = plant
            if (code, family) not in existing_fam:
                db.add(ItemFamily(item_code=code, family=family))
                existing_fam.add((code, family))
            cl = classification.classify(_text(r[23]) or "", int(r[17] or 0), rs.class_matrix)
            results.append(AnalysisResult(
                run_id=arun.id, item_code=code, family=family, is_primary=(it.abc_family == family),
                monthly=[_num(v) for v in r[3:15]], total=_num(r[15]) or 0.0, share=_num(r[16]) or 0.0,
                frequency=int(r[17] or 0), frequency_pct=_num(r[20]) or 0.0, rank=int(r[0] or n),
                cum_items_pct=_num(r[18]) or 0.0, cum_demand_pct=_num(r[19]) or 0.0, qty_class=_text(r[21]) or "",
                freq_class=_text(r[22]) or "", category=_text(r[23]) or "", declared_type=_text(r[24]),
                action=_text(r[25]), classification=_text(r[26]), interval_days=cl.interval_days,
                amc=_num(r[27]) or 0.0))
        stats["families"][family] = n
    # keep only the first result per (code, family) (a code listed twice on one sheet is a DQ issue)
    uniq = {}
    for res in results:
        uniq.setdefault((res.item_code, res.family), res)
    db.add_all(uniq.values())
    arun.stats = {"results": len(uniq), "source": "legacy workbook", "period": Period(LEGACY_ABC_START, 11).label()}
    if approve_legacy_run:
        for prev in db.scalars(select(AnalysisRun).where(AnalysisRun.status == "approved")):
            prev.status = "superseded"
        arun.status, arun.approved_at, arun.approved_by_id = "approved", utcnow(), user.id if user else None
    stats.update(analysis_run_id=arun.id, demand_batch_id=batch.id, results=len(uniq))
    wb.close()
    return _finish(db, user, run, stats)


# ------------------------------------------------------------------ legacy: Masterlist workbook
def import_master_workbook(db: Session, user: User | None, path: Path, force: bool = False) -> SyncRun:
    data = path.read_bytes()
    run = _begin_import(db, user, "legacy_master", path.name, sha256_of(data), force)
    wb = load_workbook(path, data_only=True, read_only=True)
    items = _Items(db)
    seen, dupes, created = set(), 0, 0
    used: dict[str, tuple] = {}
    for r in wb["Master"].iter_rows(min_row=2, max_col=21, values_only=True):
        code = _text(r[0])
        if not code:
            continue
        if code in seen:
            dupes += 1
            continue
        seen.add(code)
        it = items.by_code.get(code)
        if it is None:
            it = items.create(code, description=_text(r[1]) or "", source="legacy")
            created += 1
        it.tracked = True
        it.description = it.description or (_text(r[1]) or "")
        uom = _text(r[9])
        if uom and uom != "- not found" and not it.uom_name:
            it.uom_name = uom
        sec, plant, remark = _text(r[5]), _text(r[6]), _text(r[19])
        if sec not in (None, "0"):
            it.material_section = sec
        if plant not in (None, "0"):
            it.plant_location = plant
        if remark and remark != "-":
            it.remark, it.is_jit = remark, remark.upper() == "JIT"
        used.setdefault(code, (_text(r[2]), _text(r[3])))
    wb.close()
    realigned = _align_primary_family(db, used)
    return _finish(db, user, run, {"items": len(seen), "duplicate_rows_skipped": dupes, "items_created": created,
                                   "primary_family_realigned": realigned})


def _align_primary_family(db: Session, used: dict[str, tuple]) -> int:
    """For codes in several ABC families, make the primary family the one whose legacy result the
    Masterlist actually carries (its ACTION / CLASSIFICATION), so migration preserves current practice."""
    from collections import Counter
    multi = {c for c, n in Counter(db.scalars(select(ItemFamily.item_code))).items() if n > 1}
    run = db.scalars(select(AnalysisRun).where(AnalysisRun.source == "legacy_import").order_by(AnalysisRun.id.desc())).first()
    if run is None or not multi:
        return 0
    n = 0
    by_code: dict[str, list[AnalysisResult]] = defaultdict(list)
    for res in db.scalars(select(AnalysisResult).where(AnalysisResult.run_id == run.id, AnalysisResult.item_code.in_(multi))):
        by_code[res.item_code].append(res)
    for code, results in by_code.items():
        want = used.get(code)
        match = next((r for r in results if (r.action, r.classification) == want), None)
        if match is None:
            continue
        it = db.scalars(select(Item).where(Item.code == code)).first()
        if it.abc_family != match.family:
            it.abc_family = match.family
            n += 1
        for r in results:
            r.is_primary = r is match
    return n


# ------------------------------------------------------------------ legacy: COUNTED LIST workbook
def import_counted_list(db: Session, user: User | None, path: Path, force: bool = False) -> SyncRun:
    data = path.read_bytes()
    run = _begin_import(db, user, "legacy_counted_list", path.name, sha256_of(data), force)
    tz = ZoneInfo(get_settings().app_timezone)
    wb = load_workbook(path, data_only=True, read_only=True)
    items = _Items(db)
    stats = {"odoo_downloads": 0, "sessions": 0, "entries": 0, "unknown_codes": 0, "duplicate_lines": 0}

    # ODOO inv → one snapshot per download date (both buckets, zeros kept: the row proves presence)
    by_dl: dict[date, dict] = defaultdict(lambda: {"lines": {}, "remark": None})
    for r in wb["ODOO inv"].iter_rows(min_row=2, max_col=6, values_only=True):
        d, code = _date(r[0]), _text(r[1])
        if not (d and code):
            continue
        g = by_dl[d]
        g["remark"] = g["remark"] or _text(r[5])
        g["lines"].setdefault(code, (_num(r[3]), _num(r[4])))
    for d, g in sorted(by_dl.items()):
        snap = InventorySnapshot(taken_at=datetime.combine(d, time(12), tz).astimezone(timezone.utc),
                                 source="excel_import", label=f"ODOO inv download {d:%Y-%m-%d} {g['remark'] or ''}".strip(),
                                 complete=False, sync_run_id=run.id)
        db.add(snap)
        db.flush()
        n = 0
        for code, (wh, prod) in g["lines"].items():
            for bucket, q in ((WAREHOUSE, wh), (PRODUCTION, prod)):
                if q is not None:
                    db.add(SnapshotLine(snapshot_id=snap.id, item_code=code, bucket=bucket, qty=q))
                    n += 1
        snap.line_count = n
        stats["odoo_downloads"] += 1

    # LIST → sessions per (date, counter); per-date snapshot of the Odoo values pasted on the lines
    groups: dict[tuple[date, str], list] = defaultdict(list)
    for r in wb["LIST"].iter_rows(min_row=2, max_col=21, values_only=True):
        d, code = _date(r[0]), _text(r[1])
        if d and code:
            groups[(d, _text(r[6]) or "Unknown")].append(r)
    wb.close()
    legacy_snaps: dict[date, InventorySnapshot] = {}
    first_line: dict[tuple[date, str], tuple] = {}
    class_at: dict[tuple[str, date], str] = {}
    line_count: dict[tuple[date, str], int] = defaultdict(int)
    touched: set[tuple[str, date]] = set()
    for (d, who), rows in sorted(groups.items()):
        sess = CountSession(count_date=d, counted_by_name=who, status="finalized", source="legacy_import",
                            created_by_id=user.id if user else None, submitted_at=utcnow(), finalized_at=utcnow(),
                            finalized_by_id=user.id if user else None,
                            remarks=f"Imported from {path.name} (LIST)")
        db.add(sess)
        db.flush()
        stats["sessions"] += 1
        for r in rows:
            raw = _text(r[1])
            it = items.get(raw)
            if it is None:
                it = items.create(raw, description="", source="legacy_count", tracked=False)
                dq.flag(db, "unknown_item_code", raw, "Counted in COUNTED LIST but absent from the Masterlist", "warning",
                        "import")
                stats["unknown_codes"] += 1
            code = it.code
            line_count[(d, code)] += 1
            first_line.setdefault((d, code), (_num(r[15]), _num(r[16])))
            if _text(r[20]) in classification.MOVEMENT_CLASSES:
                class_at.setdefault((code, d), _text(r[20]))
            remark = _text(r[5])
            added = 0
            for i, bucket, slot in [(7 + k, WAREHOUSE, str(k + 1)) for k in range(4)] + \
                                   [(11 + k, PRODUCTION, str(k + 1)) for k in range(4)]:
                q = _num(r[i])
                if q is None:
                    continue
                db.add(CountEntry(session_id=sess.id, item_code=code, bucket=bucket, slot=slot, qty=q,
                                  uom_name=it.uom_name, remarks=remark, created_by_id=user.id if user else None))
                remark = None
                added += 1
                stats["entries"] += 1
            if not added:
                # Excel treats such a line as a count of 0 (SUMIFS); OICAS does not invent a zero (BR-22).
                dq.flag(db, "count_line_without_qty", f"{d:%Y-%m-%d}/{code}",
                        f"LIST line by {who} has no quantity in WH-1..4 / PROD-1..4; not treated as a count", "warning",
                        "import")
                stats["lines_without_qty"] = stats.get("lines_without_qty", 0) + 1
                continue
            touched.add((code, d))
        legacy_snaps.setdefault(d, None)
    for (d, code), n in line_count.items():
        if n > 1:
            dq.flag(db, "duplicate_count_line", f"{d:%Y-%m-%d}/{code}", f"{n} LIST lines; quantities are summed (legacy "
                    "SUMIFS) and the first line's Odoo balance is used", "info", "import")
            stats["duplicate_lines"] += 1
    for d in sorted(legacy_snaps):
        snap = InventorySnapshot(taken_at=datetime.combine(d, time(12), tz).astimezone(timezone.utc),
                                 source="legacy_list", label=f"Odoo balances pasted in COUNTED LIST {d:%Y-%m-%d}",
                                 complete=False, sync_run_id=run.id)
        db.add(snap)
        db.flush()
        n = 0
        for (dd, code), (wh, prod) in first_line.items():
            if dd != d:
                continue
            for bucket, q in ((WAREHOUSE, wh), (PRODUCTION, prod)):
                if q is not None:
                    db.add(SnapshotLine(snapshot_id=snap.id, item_code=code, bucket=bucket, qty=q))
                    n += 1
        snap.line_count = n
        legacy_snaps[d] = snap
        for s in db.scalars(select(CountSession).where(CountSession.count_date == d,
                                                       CountSession.source == "legacy_import",
                                                       CountSession.snapshot_id.is_(None))):
            s.snapshot_id = snap.id
    db.flush()
    ctx = counting.RecomputeContext(db)
    for code, d in sorted(touched, key=lambda t: (t[1], t[0])):
        rc = counting.recompute(db, code, d, ctx)
        if rc is not None and class_at.get((code, d)):
            rc.classification_at_count = class_at[(code, d)]
    stats["reconciliations"] = len(touched)
    return _finish(db, user, run, stats)


def import_reference_set(db: Session, user: User | None, ref_dir: Path, force: bool = False) -> list[SyncRun]:
    runs = [
        import_amc_workbook(db, user, ref_dir / "03_AMC Sep-Jul  ABC Analysis.xlsx", force),
        import_master_workbook(db, user, ref_dir / "10.13.26 INVENTORY MASTERLIST & CYCLE COUNT TRACKER.xlsx", force),
        import_counted_list(db, user, ref_dir / "COUNTED LIST.xlsx", force),
    ]
    dq.scan_items(db)
    return runs


# ------------------------------------------------------------------ count sheet (template + upload)
SHEET_HEADERS = ["RM CODE", "DESCRIPTION", "UoM", "PLANT LOCATION", "COUNT (WH-1)", "COUNT (WH-2)", "COUNT (WH-3)",
                 "COUNT (WH-4)", "COUNT (PROD-1)", "COUNT (PROD-2)", "COUNT (PROD-3)", "COUNT (PROD-4)", "REMARKS"]
HEADER_ROW = 6


def count_sheet_workbook(rows: list[dict], title: str, plan_id: int | None) -> Workbook:
    """Printable/fillable count sheet in the layout counters already use (LIST columns H..O)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "COUNT SHEET"
    ws["A1"], ws["B1"] = "Count sheet", title
    ws["A2"], ws["A3"], ws["A4"] = "Count date (YYYY-MM-DD)", "Counted by", "Plan #"
    ws["B4"] = plan_id
    ws["A1"].font = Font(bold=True, size=14)
    fill = PatternFill("solid", fgColor="D9EAD3")
    for c, h in enumerate(SHEET_HEADERS, start=1):
        cell = ws.cell(HEADER_ROW, c, h)
        cell.font, cell.fill = Font(bold=True), fill
        cell.alignment = Alignment(wrap_text=True, horizontal="center")
    for i, r in enumerate(rows, start=HEADER_ROW + 1):
        ws.cell(i, 1, r["code"])
        ws.cell(i, 2, r.get("description"))
        ws.cell(i, 3, r.get("uom"))
        ws.cell(i, 4, r.get("plant_location"))
    widths = [16, 50, 8, 10] + [11] * 8 + [30]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    ws.freeze_panes = ws.cell(HEADER_ROW + 1, 2)
    ws.cell(HEADER_ROW - 1, 1, "Leave a cell blank if that location was not counted; enter 0 only for a counted zero.")
    ws.cell(HEADER_ROW - 1, 1).font = Font(italic=True, color="666666")
    return wb


def parse_count_sheet(fp: BinaryIO) -> tuple[dict, list[dict], list[str]]:
    """Returns (meta, entries, errors). Entries: {row, code, bucket, slot, qty, remarks}."""
    wb = load_workbook(fp, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(min_row=1, max_col=len(SHEET_HEADERS), values_only=True))
    wb.close()
    errors: list[str] = []
    meta = {"count_date": _date(rows[1][1]) if len(rows) > 1 else None,
            "counted_by": _text(rows[2][1]) if len(rows) > 2 else None,
            "plan_id": int(rows[3][1]) if len(rows) > 3 and isinstance(rows[3][1], (int, float)) else None}
    if len(rows) < HEADER_ROW or [(_text(h) or "").upper() for h in rows[HEADER_ROW - 1][:len(SHEET_HEADERS)]] != SHEET_HEADERS:
        return meta, [], ["the file is not an OICAS count sheet (header row 6 does not match the template)"]
    entries = []
    for n, r in enumerate(rows[HEADER_ROW:], start=HEADER_ROW + 1):
        code = _text(r[0])
        if not code:
            continue
        remark = _text(r[12])
        for i in range(8):
            v = r[4 + i]
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            q = _num(v)
            if q is None:
                try:
                    q = float(str(v).replace(",", ""))
                except ValueError:
                    errors.append(f"row {n}: {SHEET_HEADERS[4 + i]} value {v!r} is not a number")
                    continue
            if q < 0:
                errors.append(f"row {n}: negative quantity in {SHEET_HEADERS[4 + i]}")
                continue
            entries.append({"row": n, "code": code, "bucket": WAREHOUSE if i < 4 else PRODUCTION,
                            "slot": str(i % 4 + 1), "qty": q, "remarks": remark})
            remark = None
    return meta, entries, errors


def upload_count_sheet(db: Session, user: User, fp: BinaryIO, filename: str, count_date: date | None,
                       counted_by: str | None, plan_id: int | None, client_token: str | None) -> tuple[CountSession | None, list[str]]:
    meta, entries, errors = parse_count_sheet(fp)
    count_date = count_date or meta["count_date"]
    counted_by = counted_by or meta["counted_by"]
    plan_id = plan_id or meta["plan_id"]
    if not count_date:
        errors.append("count date is missing (cell B2 or the form)")
    if not counted_by:
        errors.append("counted by is missing (cell B3 or the form)")
    known = set(db.scalars(select(Item.code).where(Item.code.in_({e["code"] for e in entries}))))
    for e in entries:
        if e["code"] not in known:
            errors.append(f"row {e['row']}: unknown item code {e['code']!r}")
    if not entries and not errors:
        errors.append("no quantities found in the sheet")
    if errors:
        return None, errors
    s = counting.create_session(db, user, count_date, counted_by, plan_id, client_token,
                                f"Uploaded from {filename}", source="excel_upload")
    if s.entries:  # idempotent replay of the same upload
        return s, []
    for e in entries:
        counting.add_entry(db, user, s.id, e["code"], e["bucket"], e["qty"], e["slot"], 1, e["remarks"])
    return s, []


# ------------------------------------------------------------------ demand upload
def upload_demand(db: Session, user: User, fp: BinaryIO, filename: str, first_month: date | None = None) -> DemandBatch:
    """Accepts the raw Odoo export (Created on / Product Reference / Demand) or the Demand pivot."""
    data = fp.read()
    import io
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    tz = ZoneInfo(get_settings().app_timezone)
    agg: dict[tuple[str, date], float] = defaultdict(float)
    hdr_idx = next((i for i, r in enumerate(rows[:5]) if r and any(isinstance(c, str) and "Reference" in c for c in r)), None)
    if hdr_idx is None:
        raise ImportError_("no header with 'Reference' found in the first 5 rows")
    hdr = [(_text(c) or "") for c in rows[hdr_idx]]
    if any("Created on" in h for h in hdr) and any(h.endswith("Demand") for h in hdr):
        ci = next(i for i, h in enumerate(hdr) if "Created on" in h)
        ri = next(i for i, h in enumerate(hdr) if h.endswith("Reference"))
        di = next(i for i, h in enumerate(hdr) if h.endswith("Demand"))
        for r in rows[hdr_idx + 1:]:
            code, when, q = _text(r[ri]), r[ci], _num(r[di])
            if not code or q is None or not isinstance(when, (datetime, date)):
                continue
            when = when if isinstance(when, datetime) else datetime.combine(when, time())
            agg[(code, date(when.year, when.month, 1))] += q
        kind = "raw export"
    else:
        if first_month is None:
            raise ImportError_("pivot format needs the first month of the first quantity column")
        ri = next(i for i, h in enumerate(hdr) if h.endswith("Reference"))
        for r in rows[hdr_idx + 1:]:
            code = _text(r[ri])
            if not code:
                continue
            for k, v in enumerate(r[ri + 2:]):
                q = _num(v)
                if q is not None:
                    agg[(code, add_months(first_month.replace(day=1), k))] += q
        kind = "pivot"
    if not agg:
        raise ImportError_("no demand quantities found")
    months = sorted({m for _, m in agg})
    batch = DemandBatch(source="excel", label=f"{filename} ({kind})", period_start=months[0], period_end=months[-1],
                        line_count=len(agg), file_sha256=sha256_of(data), created_by_id=user.id)
    db.add(batch)
    db.flush()
    db.add_all([DemandLine(batch_id=batch.id, item_code=c, month=m, qty=q) for (c, m), q in agg.items()])
    audit.record(db, user, "import.demand", "demand_batch", batch.id, {"file": filename, "format": kind,
                                                                     "lines": len(agg), "tz": str(tz)})
    return batch


# ------------------------------------------------------------------ item attributes upload
ATTR_COLUMNS = {"RM CODE": "code", "CODE": "code", "MATERIAL SECTION": "material_section", "ABC FAMILY": "abc_family",
                "PLANT LOCATION": "plant_location", "REMARK": "remark", "TRACKED": "tracked"}


def upload_item_attributes(db: Session, user: User, fp: BinaryIO) -> tuple[int, list[str]]:
    from . import inventory
    wb = load_workbook(fp, data_only=True, read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    wb.close()
    if not rows:
        return 0, ["empty file"]
    cols = {i: ATTR_COLUMNS.get((_text(h) or "").upper()) for i, h in enumerate(rows[0])}
    if "code" not in cols.values():
        return 0, ["first row must contain a 'RM CODE' column"]
    updated, errors = 0, []
    for n, r in enumerate(rows[1:], start=2):
        vals = {cols[i]: v for i, v in enumerate(r) if cols.get(i)}
        code = _text(vals.pop("code", None))
        if not code:
            continue
        if "tracked" in vals:
            vals["tracked"] = str(vals["tracked"]).strip().lower() in ("1", "true", "yes", "y")
        vals = {k: (str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and k != "tracked" else v)
                for k, v in vals.items()}
        try:
            inventory.update_item(db, user, code, vals)
            updated += 1
        except (LookupError, ValueError) as e:
            errors.append(f"row {n} ({code}): {e}")
    return updated, errors
