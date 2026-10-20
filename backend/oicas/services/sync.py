"""Odoo → OICAS synchronisation (read-only) and snapshot access.

Inventory sync: locations, products (items), stock quants → immutable ``inventory_snapshot``.
Demand sync: MO component moves → monthly ``demand_batch`` (same basis as legacy Sheet1).
A failed sync never produces a snapshot and never alters existing data (savepoint rollback).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..engine.amc import Period
from ..engine.reconciliation import BUCKETS
from ..models import (DemandBatch, DemandLine, InventorySnapshot, Item, SnapshotLine, SnapshotQuant, StockLocation,
                      SyncRun, User, utcnow)
from ..odoo.client import OdooError, OdooGateway
from . import audit, dq, rules

log = logging.getLogger("oicas.sync")

LOCATION_FIELDS = ["complete_name", "usage", "company_id", "warehouse_id", "active"]
PRODUCT_FIELDS = ["default_code", "display_name", "name", "uom_id", "active"]
QUANT_FIELDS = ["product_id", "location_id", "quantity", "company_id"]
MOVE_FIELDS = ["product_id", "product_uom_qty", "create_date", "state"]


def _m2o_name(v) -> str | None:
    return v[1] if isinstance(v, (list, tuple)) and len(v) == 2 else None


def _m2o_id(v) -> int | None:
    return v[0] if isinstance(v, (list, tuple)) and v else (v if isinstance(v, int) else None)


def _finish(run: SyncRun, status: str, stats: dict, error: str | None = None) -> SyncRun:
    run.status, run.stats, run.error, run.finished_at = status, stats, error, utcnow()
    return run


# ------------------------------------------------------------------ inventory sync
def run_inventory_sync(db: Session, gw: OdooGateway, user: User | None = None) -> SyncRun:
    run = SyncRun(kind="inventory", mode=gw.mode, triggered_by_id=user.id if user else None,
                  scope={"locations": "usage=internal", "products": "active"})
    db.add(run)
    db.flush()
    stats: dict = {}
    try:
        with db.begin_nested():
            stats["server_version"] = gw.version().get("server_version")
            locs = _sync_locations(db, gw, stats)
            products = _sync_products(db, gw, stats)
            snap = _snapshot_quants(db, gw, run, locs, products, stats)
            from .imports import flag_not_in_odoo
            stats["tracked_items_not_in_odoo"] = flag_not_in_odoo(db)
            stats["snapshot_id"] = snap.id
            dq.auto_resolve(db, "sync_failed", set(), "sync")
            dq.auto_resolve(db, "stale_snapshot", set(), "sync")
        _finish(run, "success", stats)
    except OdooError as e:
        log.error("inventory sync %s failed: %s", run.id, e)
        _finish(run, "failed", stats, str(e))
        dq.flag(db, "sync_failed", f"inventory#{run.id}", str(e), "error", "sync")
    audit.record(db, user, "sync.inventory", "sync_run", run.id, {"status": run.status, **stats})
    return run


def _sync_locations(db: Session, gw: OdooGateway, stats: dict) -> dict[int, StockLocation]:
    by_odoo = {loc.odoo_id: loc for loc in db.scalars(select(StockLocation))}
    seen = set()
    for r in gw.search_read("stock.location", [("usage", "=", "internal")], LOCATION_FIELDS):
        loc = by_odoo.get(r["id"])
        if loc is None:
            loc = StockLocation(odoo_id=r["id"], complete_name=r["complete_name"])
            db.add(loc)
            by_odoo[r["id"]] = loc
        loc.complete_name, loc.usage = r["complete_name"], r.get("usage") or "internal"
        loc.company_name, loc.warehouse_name = _m2o_name(r.get("company_id")), _m2o_name(r.get("warehouse_id"))
        loc.active = bool(r.get("active", True))
        seen.add(r["id"])
    unmapped = {str(o) for o, loc in by_odoo.items() if o in seen and loc.bucket is None}
    for o in unmapped:
        dq.flag(db, "unmapped_location", o, f"{by_odoo[int(o)].complete_name}: map it in System Configuration → "
                "Locations; its stock is excluded until mapped", "warning", "sync")
    dq.auto_resolve(db, "unmapped_location", unmapped, "sync")
    stats["locations"], stats["unmapped_locations"] = len(seen), len(unmapped)
    db.flush()
    return {o: loc for o, loc in by_odoo.items() if o in seen}


def _sync_products(db: Session, gw: OdooGateway, stats: dict) -> dict[int, str]:
    """Upsert items from product.product; returns {odoo product id: item code}."""
    rows = list(gw.search_read("product.product", [], PRODUCT_FIELDS))
    by_code: dict[str, list[dict]] = defaultdict(list)
    no_code = []
    for r in rows:
        code = (r.get("default_code") or "").strip() if isinstance(r.get("default_code"), str) else ""
        if code:
            by_code[code].append(r)
        else:
            no_code.append(r)
    items_by_code = {i.code: i for i in db.scalars(select(Item))}
    items_by_pid = {i.odoo_product_id: i for i in items_by_code.values() if i.odoo_product_id}
    now = utcnow()
    dup_refs, changed_refs, uom_missing, created = set(), set(), set(), 0
    pid_to_code: dict[int, str] = {}
    for code, prods in by_code.items():
        prods.sort(key=lambda p: p["id"])
        if len(prods) > 1:
            dup_refs.add(code)
            dq.flag(db, "duplicate_product_code", code,
                    f"Odoo product ids {[p['id'] for p in prods]}; OICAS uses the lowest id", "warning", "sync")
        p = prods[0]
        for extra in prods:
            pid_to_code[extra["id"]] = code
        it = items_by_pid.get(p["id"])
        if it is not None and it.code != code:
            changed_refs.add(str(p["id"]))
            dq.flag(db, "product_code_changed", str(p["id"]),
                    f"OICAS item {it.code!r} now has Internal Reference {code!r} in Odoo; review before re-keying",
                    "error", "sync")
            continue
        it = it or items_by_code.get(code)
        if it is None:
            it = Item(code=code, tracked=False, source="odoo")
            db.add(it)
            items_by_code[code] = it
            created += 1
        if it.odoo_product_id is None and p["id"] not in items_by_pid:
            it.odoo_product_id = p["id"]
            items_by_pid[p["id"]] = it
        it.description = (p.get("name") or p.get("display_name") or it.description or "")[:500]
        it.uom_name = _m2o_name(p.get("uom_id")) or it.uom_name
        it.odoo_active = bool(p.get("active", True))
        it.last_synced_at = now
        if not it.uom_name:
            uom_missing.add(code)
    for r in no_code:
        dq.flag(db, "product_without_code", str(r["id"]), f"{r.get('display_name')}", "info", "sync")
    dq.auto_resolve(db, "product_without_code", {str(r["id"]) for r in no_code}, "sync")
    dq.auto_resolve(db, "duplicate_product_code", dup_refs, "sync")
    dq.auto_resolve(db, "product_code_changed", changed_refs, "sync")
    stats.update(products=len(rows), products_without_code=len(no_code), duplicate_codes=len(dup_refs),
                 items_created=created)
    db.flush()
    return pid_to_code


def _snapshot_quants(db: Session, gw: OdooGateway, run: SyncRun, locs: dict[int, StockLocation],
                     pid_to_code: dict[int, str], stats: dict) -> InventorySnapshot:
    totals: dict[tuple[str, str], float] = defaultdict(float)
    raw: list[SnapshotQuant] = []
    excluded = unknown = n = 0
    for q in gw.search_read("stock.quant", [("location_id.usage", "=", "internal")], QUANT_FIELDS):
        n += 1
        code = pid_to_code.get(_m2o_id(q.get("product_id")))
        loc_id = _m2o_id(q.get("location_id"))
        qty = float(q.get("quantity") or 0.0)
        if code is None:
            unknown += 1
            continue
        raw.append(SnapshotQuant(item_code=code, location_odoo_id=loc_id, qty=qty))
        loc = locs.get(loc_id)
        if loc is None or loc.bucket not in BUCKETS:
            excluded += 1
            continue
        totals[(code, loc.bucket)] += qty
    snap = InventorySnapshot(sync_run_id=run.id, taken_at=utcnow(), source="odoo", label=f"Odoo sync #{run.id}",
                             complete=True)
    db.add(snap)
    db.flush()
    for r in raw:
        r.snapshot_id = snap.id
    db.add_all(raw)
    lines = [SnapshotLine(snapshot_id=snap.id, item_code=c, bucket=b, qty=v) for (c, b), v in totals.items() if v != 0]
    db.add_all(lines)
    negatives = {f"{c}/{b}" for (c, b), v in totals.items() if v < 0}
    for ref in negatives:
        dq.flag(db, "negative_odoo_qty", ref, f"Odoo on-hand {totals[tuple(ref.split('/'))]:g} in snapshot #{snap.id}",
                "warning", "sync")
    dq.auto_resolve(db, "negative_odoo_qty", negatives, "sync")
    snap.line_count = len(lines)
    stats.update(quants=n, quants_unknown_product=unknown, quants_unmapped_location=excluded, snapshot_lines=len(lines))
    return snap


# ------------------------------------------------------------------ demand sync
def run_demand_sync(db: Session, gw: OdooGateway, period: Period, user: User | None = None) -> SyncRun:
    tz = ZoneInfo(get_settings().app_timezone)
    start_local = datetime(period.start.year, period.start.month, 1, tzinfo=tz)
    end_month = period.months[-1]
    nxt = date(end_month.year + (end_month.month == 12), end_month.month % 12 + 1, 1)
    end_local = datetime(nxt.year, nxt.month, 1, tzinfo=tz)
    fmt = "%Y-%m-%d %H:%M:%S"
    domain = [("raw_material_production_id", "!=", False),
              ("create_date", ">=", start_local.astimezone(timezone.utc).strftime(fmt)),
              ("create_date", "<", end_local.astimezone(timezone.utc).strftime(fmt))]
    if rules.get_setting(db, "odoo_demand_exclude_cancelled"):
        domain.append(("state", "!=", "cancel"))
    run = SyncRun(kind="demand", mode=gw.mode, triggered_by_id=user.id if user else None,
                  scope={"period": period.label(), "domain": [list(d) for d in domain]})
    db.add(run)
    db.flush()
    stats: dict = {}
    try:
        with db.begin_nested():
            pid_code = {i.odoo_product_id: i.code for i in db.scalars(select(Item).where(Item.odoo_product_id.isnot(None)))}
            agg: dict[tuple[str, date], float] = defaultdict(float)
            unknown, n = set(), 0
            for mv in gw.search_read("stock.move", domain, MOVE_FIELDS):
                n += 1
                pid = _m2o_id(mv.get("product_id"))
                code = pid_code.get(pid)
                if code is None:
                    unknown.add(str(pid))
                    continue
                created = datetime.strptime(mv["create_date"], fmt).replace(tzinfo=timezone.utc).astimezone(tz)
                agg[(code, date(created.year, created.month, 1))] += float(mv.get("product_uom_qty") or 0.0)
            batch = DemandBatch(source="odoo", label=f"Odoo MO component demand {period.label()}",
                                period_start=period.start, period_end=period.end, sync_run_id=run.id,
                                created_by_id=user.id if user else None)
            db.add(batch)
            db.flush()
            db.add_all([DemandLine(batch_id=batch.id, item_code=c, month=m, qty=q) for (c, m), q in agg.items()])
            batch.line_count = len(agg)
            for pid in unknown:
                dq.flag(db, "unknown_item_code", f"odoo-product:{pid}", "Demand move for a product not synced as an item",
                        "info", "demand_sync")
            stats.update(moves=n, lines=len(agg), unknown_products=len(unknown), demand_batch_id=batch.id)
        _finish(run, "success", stats)
    except OdooError as e:
        _finish(run, "failed", stats, str(e))
        dq.flag(db, "sync_failed", f"demand#{run.id}", str(e), "error", "sync")
    audit.record(db, user, "sync.demand", "sync_run", run.id, {"status": run.status, **stats})
    return run


# ------------------------------------------------------------------ snapshot access
def latest_snapshot(db: Session, source: str | None = "odoo") -> InventorySnapshot | None:
    q = select(InventorySnapshot)
    if source:
        q = q.where(InventorySnapshot.source == source)
    return db.scalars(q.order_by(InventorySnapshot.taken_at.desc(), InventorySnapshot.id.desc())).first()


def snapshot_at(db: Session, when: datetime) -> InventorySnapshot | None:
    """Latest Odoo snapshot taken at or before ``when``."""
    return db.scalars(select(InventorySnapshot).where(InventorySnapshot.source == "odoo",
                                                      InventorySnapshot.taken_at <= when)
                      .order_by(InventorySnapshot.taken_at.desc())).first()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def staleness(db: Session, snap: InventorySnapshot | None) -> dict:
    hours = float(rules.get_setting(db, "odoo_stale_after_hours") or 24)
    last_ok = db.scalars(select(SyncRun).where(SyncRun.kind == "inventory", SyncRun.status == "success")
                         .order_by(SyncRun.finished_at.desc())).first()
    last_run = db.scalars(select(SyncRun).where(SyncRun.kind == "inventory").order_by(SyncRun.started_at.desc())).first()
    if snap is None:
        return {"snapshot": None, "stale": True, "age_hours": None, "threshold_hours": hours, "last_success": last_ok,
                "last_run": last_run}
    age = (utcnow() - _aware(snap.taken_at)).total_seconds() / 3600
    return {"snapshot": snap, "stale": age > hours, "age_hours": age, "threshold_hours": hours,
            "last_success": last_ok, "last_run": last_run}


def balances(db: Session, snap: InventorySnapshot | None, codes: list[str]) -> dict[str, dict[str, float | None]]:
    """Odoo balance per item and bucket from a snapshot.

    line present → its qty; complete Odoo snapshot and product known to Odoo → 0.0; otherwise ``None``.
    """
    out = {c: {b: None for b in BUCKETS} for c in codes}
    if snap is None or not codes:
        return out
    known: set[str] = set()
    if snap.complete:
        known = set(db.scalars(select(Item.code).where(Item.code.in_(codes), Item.odoo_product_id.isnot(None))))
        for c in known:
            out[c] = {b: 0.0 for b in BUCKETS}
    for chunk in range(0, len(codes), 900):
        part = codes[chunk:chunk + 900]
        for ln in db.scalars(select(SnapshotLine).where(SnapshotLine.snapshot_id == snap.id,
                                                        SnapshotLine.item_code.in_(part))):
            out[ln.item_code][ln.bucket] = ln.qty
    return out


BOOK_SOURCE = "manual_import"


def book_balances(db: Session, code: str, on: date) -> dict[str, float | None]:
    """Latest imported book balance per bucket dated on or before ``on`` (for items Odoo doesn't hold)."""
    tz = ZoneInfo(get_settings().app_timezone)
    cutoff = datetime.combine(on + timedelta(days=1), datetime.min.time(), tz).astimezone(timezone.utc)
    out: dict[str, float | None] = {b: None for b in BUCKETS}
    rows = db.execute(select(SnapshotLine.bucket, SnapshotLine.qty).join(InventorySnapshot).where(
        InventorySnapshot.source == BOOK_SOURCE, InventorySnapshot.taken_at < cutoff, SnapshotLine.item_code == code)
        .order_by(InventorySnapshot.taken_at.desc(), InventorySnapshot.id.desc())).all()
    for bucket, qty in rows:
        if out.get(bucket) is None:
            out[bucket] = qty
    return out


def prune_snapshots(db: Session, keep_days: int) -> int:
    """Delete old Odoo snapshots that no reconciliation, session or report references."""
    from ..models import CountSession, Reconciliation, ReportRun
    cutoff = utcnow() - timedelta(days=keep_days)
    used = set(db.scalars(select(Reconciliation.snapshot_id).where(Reconciliation.snapshot_id.isnot(None))))
    used |= set(db.scalars(select(CountSession.snapshot_id).where(CountSession.snapshot_id.isnot(None))))
    used |= set(db.scalars(select(ReportRun.snapshot_id).where(ReportRun.snapshot_id.isnot(None))))
    latest = latest_snapshot(db)
    n = 0
    for s in db.scalars(select(InventorySnapshot).where(InventorySnapshot.source == "odoo",
                                                        InventorySnapshot.taken_at < cutoff)):
        if s.id not in used and (latest is None or s.id != latest.id):
            db.query(SnapshotLine).filter(SnapshotLine.snapshot_id == s.id).delete()
            db.query(SnapshotQuant).filter(SnapshotQuant.snapshot_id == s.id).delete()
            db.delete(s)
            n += 1
    return n
