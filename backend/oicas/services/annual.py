"""Annual Inventory log: entries per period (P1-P4), area (Warehouse/Production) and section.

A plain log kept apart from count sessions. Every change writes an audit row, and each entry keeps
who created / last changed it, so a later reconciliation can trace and use the figures.
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AnnualInventoryEntry, AuditLog, Item, SnapshotQuant, StockLocation, User, utcnow
from . import audit, sync

PERIODS = ("P1", "P2", "P3", "P4")
PERIOD_LABELS = {p: f"Plant {p[1:]}" for p in PERIODS}
AREAS = {"WAREHOUSE": "Warehouse", "PRODUCTION": "Production"}
SECTIONS = (1, 2)  # same for every period and area
MAX_ROWS = 1000
START_NO = 40900  # first Entry No. of every section; the series then runs +1 until someone types a different number
NO_RE = re.compile(r"^\d{1,9}$")
QTY_RE = re.compile(r"^(\d+(\.\d+)?|\.\d+)$")  # plain non-negative decimal, thousands commas removed first


class AnnualError(ValueError):
    pass


def parse_scope(period: str | None, area: str | None = None,
                section: str | int | None = None) -> tuple[str | None, str | None, int | None]:
    """Strictly parse a (period, area, section) selection, case-insensitively. A part that is unknown
    (or given without its parent) comes back as None, so callers can fall back to the deepest valid level."""
    p = (period or "").upper()
    if p not in PERIODS:
        return None, None, None
    a = (area or "").upper()
    if a not in AREAS:
        return p, None, None
    try:
        s = int(section) if section not in (None, "") else None
    except (TypeError, ValueError):
        s = None
    return p, a, (s if s in SECTIONS else None)


def _clean(item_code: str, qty: str, location: str, remarks: str | None) -> tuple[str, float, str, str | None]:
    code, loc = (item_code or "").strip(), (location or "").strip()
    if not code:
        raise AnnualError("Item code is required.")
    if not loc:
        raise AnnualError("Location is required.")
    raw = str(qty or "").replace(",", "").strip()
    if raw.startswith("-") and QTY_RE.match(raw[1:]):
        raise AnnualError("Quantity cannot be negative.")
    if not QTY_RE.match(raw):
        raise AnnualError("Quantity must be a number (e.g. 12 or 1,250.5).")
    q = float(raw)
    return code, q, loc, (remarks or "").strip() or None


def entries(db: Session, period: str, area: str | None = None, section: int | None = None,
            limit: int | None = MAX_ROWS) -> list[AnnualInventoryEntry]:
    """Newest first. ``limit=None`` returns every row (used by the Excel export)."""
    stmt = select(AnnualInventoryEntry).where(AnnualInventoryEntry.period == period)
    if area:
        stmt = stmt.where(AnnualInventoryEntry.area == area)
    if section:
        stmt = stmt.where(AnnualInventoryEntry.section == section)
    stmt = stmt.order_by(AnnualInventoryEntry.id.desc())
    return list(db.scalars(stmt.limit(limit) if limit else stmt))


def summary(db: Session) -> dict[tuple, tuple[int, datetime | None]]:
    """(count, last logged at) per (period, area, section); the choice pages roll these up."""
    rows = db.execute(select(AnnualInventoryEntry.period, AnnualInventoryEntry.area, AnnualInventoryEntry.section,
                             func.count(), func.max(AnnualInventoryEntry.created_at))
                      .group_by(AnnualInventoryEntry.period, AnnualInventoryEntry.area, AnnualInventoryEntry.section)).all()
    return {(p, a, s): (n, last) for p, a, s, n, last in rows}


def rollup(summ: dict, period: str | None = None, area: str | None = None, section: int | None = None) -> tuple[int, datetime | None]:
    """Total count and latest time over the summary keys matching the given prefix."""
    n, last = 0, None
    for (p, a, s), (c, t) in summ.items():
        if (period and p != period) or (area and a != area) or (section and s != section):
            continue
        n += c
        if t and (last is None or t > last):
            last = t
    return n, last


def next_entry_no(db: Session, period: str, area: str, section: int) -> int:
    """The number the next entry of this section gets: one more than the highest used, or 40900 for the first.

    Typing a higher number (say 40910) therefore continues from there (40911, 40912, ...), and a number freed
    by a deleted entry is handed out again only when it was the highest.
    """
    top = db.scalar(select(func.max(AnnualInventoryEntry.entry_no)).where(
        AnnualInventoryEntry.period == period, AnnualInventoryEntry.area == area, AnnualInventoryEntry.section == section))
    return START_NO if top is None else top + 1


def _parse_no(value: str | int | None) -> int | None:
    """Entry No. as typed: blank means 'assign the next one'; otherwise a whole number of up to 9 digits."""
    raw = str(value if value is not None else "").strip()
    if raw == "":
        return None
    if not NO_RE.match(raw) or int(raw) == 0:
        raise AnnualError("Entry No. must be a whole number (digits only), e.g. 40900.")
    return int(raw)


def _no_taken(db: Session, period: str, area: str, section: int, no: int, exclude_id: int | None = None) -> bool:
    stmt = select(AnnualInventoryEntry.id).where(
        AnnualInventoryEntry.period == period, AnnualInventoryEntry.area == area,
        AnnualInventoryEntry.section == section, AnnualInventoryEntry.entry_no == no)
    if exclude_id is not None:
        stmt = stmt.where(AnnualInventoryEntry.id != exclude_id)
    return db.scalar(stmt.limit(1)) is not None


def add(db: Session, user: User, period: str, area: str, section: int, item_code: str, qty: str, location: str,
        remarks: str | None = None, ip: str | None = None, entry_no: str | int | None = None) -> AnnualInventoryEntry:
    p, a, s = parse_scope(period, area, section)
    if s is None:
        raise AnnualError("Unknown period, area or section.")
    code, q, loc, rem = _clean(item_code, qty, location, remarks)
    no = _parse_no(entry_no)
    if no is None:
        no = next_entry_no(db, p, a, s)
    elif _no_taken(db, p, a, s, no):
        raise AnnualError(f"Entry No. {no} is already used in this section.")
    e = AnnualInventoryEntry(period=p, area=a, section=s, entry_no=no, item_code=code, qty=q, location=loc, remarks=rem,
                             created_by_id=user.id)
    db.add(e)
    try:
        db.flush()
    except IntegrityError:  # two people took the same number at the same moment
        raise AnnualError(f"Entry No. {no} was just taken by someone else. Try again.") from None
    audit.record(db, user, "annual.add", "annual_inventory_entry", e.id,
                 {"period": p, "area": a, "section": s, "entry_no": no, "item_code": code, "qty": q, "location": loc}, ip)
    return e


def update(db: Session, user: User, entry_id: int, item_code: str, qty: str, location: str,
           remarks: str | None = None, ip: str | None = None, entry_no: str | int | None = None) -> AnnualInventoryEntry:
    e = db.get(AnnualInventoryEntry, entry_id)
    if e is None:
        raise AnnualError("Entry not found.")
    code, q, loc, rem = _clean(item_code, qty, location, remarks)
    no = _parse_no(entry_no)  # blank keeps the current number
    if no is None:
        no = e.entry_no
    elif no != e.entry_no and _no_taken(db, e.period, e.area, e.section, no, exclude_id=e.id):
        raise AnnualError(f"Entry No. {no} is already used in this section.")
    before = {"entry_no": e.entry_no, "item_code": e.item_code, "qty": e.qty, "location": e.location, "remarks": e.remarks}
    e.entry_no, e.item_code, e.qty, e.location, e.remarks = no, code, q, loc, rem
    e.updated_at, e.updated_by_id = utcnow(), user.id
    try:
        db.flush()
    except IntegrityError:
        raise AnnualError(f"Entry No. {no} was just taken by someone else. Try again.") from None
    audit.record(db, user, "annual.edit", "annual_inventory_entry", e.id,
                 {"before": before, "after": {"entry_no": no, "item_code": code, "qty": q, "location": loc, "remarks": rem}}, ip)
    return e


def delete(db: Session, user: User, entry_id: int, ip: str | None = None) -> tuple[AnnualInventoryEntry, AuditLog]:
    """Delete an entry. The audit row keeps everything needed to bring it back (see ``restore``)."""
    e = db.get(AnnualInventoryEntry, entry_id)
    if e is None:
        raise AnnualError("Entry not found.")
    row = audit.record(db, user, "annual.delete", "annual_inventory_entry", e.id,
                       {"period": e.period, "area": e.area, "section": e.section, "entry_no": e.entry_no,
                        "item_code": e.item_code, "qty": e.qty,
                        "location": e.location, "remarks": e.remarks, "created_by_id": e.created_by_id,
                        "created_at": e.created_at}, ip)
    db.delete(e)
    db.flush()  # gives the audit row its id for the Undo link
    return e, row


def restore(db: Session, user: User, audit_id: int, ip: str | None = None) -> AnnualInventoryEntry:
    """Undo a delete made by this user: re-create the entry from its audit row (once)."""
    a = db.get(AuditLog, audit_id)
    if a is None or a.action != "annual.delete" or a.user_id != user.id:
        raise AnnualError("Nothing to undo.")
    for r in db.scalars(select(AuditLog).where(AuditLog.action == "annual.restore").order_by(AuditLog.id.desc()).limit(500)):
        if (r.detail or {}).get("from_audit") == audit_id:
            raise AnnualError("Already restored.")
    d = a.detail or {}
    try:
        created = datetime.fromisoformat(d["created_at"]) if d.get("created_at") else None
        p, ar, s = d["period"], d["area"], int(d["section"])
        no = int(d["entry_no"]) if d.get("entry_no") else next_entry_no(db, p, ar, s)  # older deletes had no number
        if _no_taken(db, p, ar, s, no):
            raise AnnualError(f"Entry No. {no} is now used by another entry, so it can't be restored.")
        e = AnnualInventoryEntry(period=p, area=ar, section=s, entry_no=no, item_code=d["item_code"],
                                 qty=float(d["qty"]), location=d["location"], remarks=d.get("remarks"),
                                 created_by_id=d.get("created_by_id"), **({"created_at": created} if created else {}))
    except (KeyError, TypeError, ValueError) as ex:
        if isinstance(ex, AnnualError):
            raise
        raise AnnualError("Nothing to undo.") from None
    db.add(e)
    try:
        db.flush()
    except IntegrityError:
        raise AnnualError(f"Entry No. {no} is now used by another entry, so it can't be restored.") from None
    audit.record(db, user, "annual.restore", "annual_inventory_entry", e.id,
                 {"from_audit": audit_id, "item_code": e.item_code, "qty": e.qty, "location": e.location}, ip)
    return e


def lookup(db: Session, q: str, limit: int = 12) -> list[dict]:
    """Item codes matching ``q`` with the Odoo locations that hold them (latest Odoo snapshot).

    One row per code + location, so a click can fill both fields. Codes with no stock location in Odoo
    come back with an empty location; codes only seen in the log (typed by hand earlier) follow last.
    """
    q = q.strip()
    ql = q.casefold()
    stmt = select(Item.code, Item.description)
    if ql:
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        starts = Item.code.ilike(f"{esc}%", escape="\\")
        has = Item.code.ilike(f"%{esc}%", escape="\\")
        # codes that start with what was typed come first, then codes that merely contain it, then description matches
        stmt = (stmt.where(or_(has, Item.description.ilike(f"%{esc}%", escape="\\")))
                .order_by(case((starts, 0), (has, 1), else_=2), Item.code))
    else:  # nothing typed yet (field just clicked): tracked items first
        stmt = stmt.order_by(Item.tracked.desc(), Item.code)
    items = db.execute(stmt.limit(limit)).all()
    snap = sync.latest_snapshot(db)
    locs: dict[str, list[tuple[str, float]]] = {}
    if snap and items:
        for code, name, qty in db.execute(
                select(SnapshotQuant.item_code, StockLocation.complete_name, SnapshotQuant.qty)
                .join(StockLocation, StockLocation.odoo_id == SnapshotQuant.location_odoo_id)
                .where(SnapshotQuant.snapshot_id == snap.id, SnapshotQuant.qty > 0,
                       SnapshotQuant.item_code.in_([i.code for i in items]))
                .order_by(SnapshotQuant.qty.desc())):
            locs.setdefault(code, []).append((name[:120], qty))
    out: list[dict] = []
    for it in items:
        for name, qty in locs.get(it.code) or [("", 0.0)]:
            out.append({"code": it.code, "description": it.description or "", "location": name, "qty": qty})
    seen = {r["code"] for r in out}
    for code in suggest(db, "item_code", q, limit):
        if code not in seen:
            out.append({"code": code, "description": "", "location": "", "qty": 0.0})
    if ql:  # one ordering across Odoo items and codes typed before: starts with, then contains, then the rest
        out.sort(key=lambda r: (0 if r["code"].casefold().startswith(ql) else 1 if ql in r["code"].casefold() else 2,
                                r["code"].casefold()))
    return out[:limit * 2]


def reconcile(rows: list[AnnualInventoryEntry]) -> dict[int, dict]:
    """For entries sharing an item code (case-insensitive) in the same log: how many there are and their total.

    Keyed by entry id; codes logged once are left out. The first-logged entry is flagged ``first``.
    """
    groups: dict[str, list[AnnualInventoryEntry]] = {}
    for e in rows:
        groups.setdefault(e.item_code.casefold(), []).append(e)
    out: dict[int, dict] = {}
    for g in groups.values():
        if len(g) < 2:
            continue
        g.sort(key=lambda e: e.id)
        total = sum(e.qty for e in g)
        for n, e in enumerate(g, 1):
            out[e.id] = {"n": n, "count": len(g), "total": total, "first": n == 1}
    return out


def suggest(db: Session, field: str, q: str, limit: int = 10) -> list[str]:
    """Distinct values already in the log for ``item_code`` or ``location`` that resemble ``q``.

    Prefix matches come first, then values merely containing it; an empty ``q`` gives the most used.
    """
    col = {"item_code": AnnualInventoryEntry.item_code, "location": AnnualInventoryEntry.location}.get(field)
    if col is None:
        return []
    q = q.strip()
    stmt = select(col, func.count().label("n")).group_by(col)
    if q:
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(col.ilike(f"%{esc}%", escape="\\"))
    rows = db.execute(stmt.order_by(func.count().desc(), col).limit(200)).all()
    vals = [v for v, _ in rows]
    if q:
        ql = q.casefold()
        vals.sort(key=lambda v: (not v.casefold().startswith(ql), v.casefold().find(ql)))
    return vals[:limit]
