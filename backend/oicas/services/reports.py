"""Report Center (docs/analysis/07-report-catalog.md).

Each report builds one ``ReportResult``. The screen, the Excel export and the PDF export all
render that same object, so exported values always equal what's on screen.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine import classification as cls_mod
from ..engine.amc import Period, add_months
from ..models import (AnalysisResult, AnalysisRun, AuditLog, CountEntry, CountPlan, CountPlanItem, CountSession,
                      DiscrepancyNote, DqException, Item, Reconciliation, SyncRun, User)
from . import analysis, dq, inventory, sync


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"  # text/int/qty/pct/date/datetime/bool
    total: bool = False


@dataclass
class Filter:
    name: str
    label: str
    kind: str = "text"  # text / select / date / int
    options: Callable[[Session], list] | None = None


@dataclass
class ReportResult:
    key: str
    title: str
    columns: list[Column]
    rows: list[dict]
    summary: list[tuple[str, object, str]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    link: str | None = None  # row link pattern, e.g. "/items/{code}"

    def totals(self) -> dict:
        out = {}
        for c in self.columns:
            if c.total:
                out[c.key] = sum(r.get(c.key) or 0 for r in self.rows)
        return out


@dataclass
class ReportDef:
    key: str
    number: int
    title: str
    description: str
    filters: list[Filter]
    build: Callable[[Session, dict], ReportResult]
    landscape: bool = True


REGISTRY: dict[str, ReportDef] = {}


def register(key, number, title, description, filters=()):
    def deco(fn):
        REGISTRY[key] = ReportDef(key, number, title, description, list(filters), fn)
        return fn
    return deco


def _d(v) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def _date_range(p: dict, default_days: int = 90) -> tuple[date, date]:
    end = _d(p.get("date_to")) or date.today()
    start = _d(p.get("date_from")) or end - timedelta(days=default_days)
    return start, end


def _opts(values):
    return lambda db: values


def _setting_opts(key):
    def f(db):
        from . import rules
        return rules.get_setting(db, key)
    return f


def _users(db):
    return [(u.id, u.name or u.login) for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))]


def _run_opts(db):
    return [(r.id, f"#{r.id} {r.status} – {Period(r.period_start, r.months).label()} ({r.source})")
            for r in db.scalars(select(AnalysisRun).order_by(AnalysisRun.id.desc()))]


def _plan_opts(db):
    return [(p.id, f"#{p.id} {p.name} ({p.status})") for p in db.scalars(select(CountPlan).order_by(CountPlan.id.desc()))]


CLASS_F = Filter("classification", "Movement class", "select", _opts(list(cls_mod.MOVEMENT_CLASSES)))
ACTION_F = Filter("action", "Action", "select", _opts(list(cls_mod.ACTIONS)))
SECTION_F = Filter("material_section", "Material section", "select", _setting_opts("material_sections"))
FAMILY_F = Filter("abc_family", "ABC family", "select", _setting_opts("abc_families"))
PLANT_F = Filter("plant_location", "Plant location", "select", _setting_opts("plant_locations"))
FROM_F, TO_F = Filter("date_from", "From", "date"), Filter("date_to", "To", "date")
Q_F = Filter("q", "Search code / description")
RUN_F = Filter("run_id", "Analysis run", "select", _run_opts)

MASTER_COLUMNS = [
    Column("code", "RM Code"), Column("description", "Description"), Column("action", "Action"),
    Column("classification", "Classification"), Column("category", "Category"), Column("amc", "AMC", "qty"),
    Column("material_section", "Material Section"), Column("abc_family", "ABC Family"),
    Column("plant_location", "Plant Location"), Column("interval_days", "Interval (days)", "int"),
    Column("uom", "UoM"), Column("last_count_date", "Counted Date", "date"), Column("next_due", "Next Count", "date"),
    Column("due_status", "Schedule"), Column("phys_wh", "Actual Count (WH)", "qty"),
    Column("phys_prod", "Actual Count (PROD)", "qty"), Column("stock_in_months", "Stock in Months", "qty"),
    Column("odoo_wh", "Odoo WH", "qty"), Column("odoo_prod", "Odoo Pre-Prod", "qty"),
    Column("disc_wh", "Discrepancy (WH)", "qty"), Column("disc_prod", "Discrepancy (PROD)", "qty"),
    Column("recon_status", "Reconciliation"), Column("review_status", "Review"), Column("remark", "Remark"),
]


def _master_meta(ds: inventory.Dataset, db: Session, p: dict) -> dict:
    snap = sync.latest_snapshot(db)
    return {"as_of": ds.as_of, "analysis_run_id": ds.run_id, "analysis_period": ds.run_period,
            "rule_set_version": ds.rule_set_version, "latest_odoo_snapshot": snap.id if snap else None,
            "filters": {k: v for k, v in p.items() if v not in (None, "")}}


# 1 ------------------------------------------------------------------------------------------
@register("masterlist", 1, "Inventory Masterlist",
          "Item details, classification, AMC, interval, latest physical and Odoo quantities, discrepancies, next count.",
          [Q_F, CLASS_F, ACTION_F, SECTION_F, FAMILY_F, PLANT_F,
           Filter("due_status", "Schedule", "select", _opts(["overdue", "due_today", "upcoming", "scheduled", "unscheduled"])),
           Filter("counted", "Counted", "select", _opts(["yes", "no"])),
           Filter("discrepancy", "Discrepancy", "select", _opts(["yes", "no"]))])
def r_masterlist(db: Session, p: dict) -> ReportResult:
    ds = inventory.build(db)
    rows = inventory.apply_filters(ds.rows, p)
    return ReportResult("masterlist", "Inventory Masterlist", MASTER_COLUMNS, [r.as_dict() for r in rows],
                        [("Items", len(rows), "int"), ("Counted", sum(r.counted for r in rows), "int"),
                         ("With discrepancy", sum(r.counted and r.has_discrepancy for r in rows), "int")],
                        _master_meta(ds, db, p), "/items/{code}")


# 2 ------------------------------------------------------------------------------------------
@register("count_sheet", 2, "Inventory Count Sheet",
          "Printable count sheet for a plan (or for due/overdue items) with blank count fields.",
          [Filter("plan_id", "Count plan", "select", _plan_opts), PLANT_F, SECTION_F,
           Filter("assigned_to_id", "Assigned to", "select", _users)])
def r_count_sheet(db: Session, p: dict) -> ReportResult:
    ds = {r.code: r for r in inventory.build(db).rows}
    plan_id = int(p["plan_id"]) if p.get("plan_id") else None
    if plan_id:
        q = select(CountPlanItem).where(CountPlanItem.plan_id == plan_id)
        if p.get("assigned_to_id"):
            q = q.where(CountPlanItem.assigned_to_id == int(p["assigned_to_id"]))
        codes = [pi.item_code for pi in db.scalars(q.order_by(CountPlanItem.priority, CountPlanItem.item_code))]
        title = f"Inventory Count Sheet – plan #{plan_id}"
    else:
        codes = [r.code for r in sorted(ds.values(), key=lambda r: (r.next_due or date.max, r.code))
                 if r.due_status in ("overdue", "due_today")]
        title = "Inventory Count Sheet – items due"
    rows = []
    for c in codes:
        r = ds.get(c)
        if r is None:
            continue
        if p.get("plant_location") and r.plant_location != p["plant_location"]:
            continue
        if p.get("material_section") and r.material_section != p["material_section"]:
            continue
        rows.append({"code": c, "description": r.description, "uom": r.uom, "plant_location": r.plant_location,
                     "wh": "", "prod": "", "counted_by": "", "remarks": ""})
    cols = [Column("code", "RM Code"), Column("description", "Description"), Column("uom", "UoM"),
            Column("plant_location", "Plant"), Column("wh", "Count WH"), Column("prod", "Count PROD"),
            Column("counted_by", "Counted by / date"), Column("remarks", "Remarks")]
    return ReportResult("count_sheet", title, cols, rows, [("Items", len(rows), "int")],
                        {"plan_id": plan_id, "note": "Blank = not counted. Write 0 only for a counted zero."})


# 3 ------------------------------------------------------------------------------------------
@register("physical_count", 3, "Physical Inventory Count Report",
          "Every count entry with its session, date, location, slot, counter, status and corrections.",
          [FROM_F, TO_F, Q_F, Filter("status", "Session status", "select",
                                     _opts(["draft", "submitted", "finalized", "cancelled"])),
           Filter("counted_by", "Counted by")])
def r_physical(db: Session, p: dict) -> ReportResult:
    start, end = _date_range(p)
    q = select(CountEntry, CountSession).join(CountSession).where(CountSession.count_date >= start,
                                                                  CountSession.count_date <= end)
    if p.get("status"):
        q = q.where(CountSession.status == p["status"])
    if p.get("counted_by"):
        q = q.where(CountSession.counted_by_name.ilike(f"%{p['counted_by']}%"))
    if p.get("q"):
        q = q.where(CountEntry.item_code.ilike(f"%{p['q']}%"))
    desc = dict(db.execute(select(Item.code, Item.description)).all())
    rows = [{"count_date": s.count_date, "session_id": s.id, "status": s.status, "counted_by": s.counted_by_name,
             "code": e.item_code, "description": desc.get(e.item_code, ""), "bucket": e.bucket, "slot": e.slot,
             "round": e.round, "qty": e.qty, "uom": e.uom_name,
             "state": "superseded" if (e.superseded_by_id or e.superseded_at) else "active",
             "correction_reason": e.correction_reason, "remarks": e.remarks}
            for e, s in db.execute(q.order_by(CountSession.count_date.desc(), CountSession.id, CountEntry.id)).all()]
    active = [r for r in rows if r["state"] == "active"]
    cols = [Column("count_date", "Date", "date"), Column("session_id", "Session", "int"), Column("status", "Status"),
            Column("counted_by", "Counted by"), Column("code", "RM Code"), Column("description", "Description"),
            Column("bucket", "Location"), Column("slot", "Slot"), Column("round", "Round", "int"),
            Column("qty", "Qty", "qty"), Column("uom", "UoM"), Column("state", "Entry"),
            Column("correction_reason", "Correction reason"), Column("remarks", "Remarks")]
    return ReportResult("physical_count", "Physical Inventory Count Report", cols, rows,
                        [("Entries", len(rows), "int"), ("Active entries", len(active), "int"),
                         ("Sessions", len({r['session_id'] for r in rows}), "int"),
                         ("Items", len({r['code'] for r in active}), "int")],
                        {"period": f"{start} – {end}"}, "/items/{code}")


RECON_COLUMNS = [Column("count_date", "Count date", "date"), Column("code", "RM Code"),
                 Column("description", "Description"), Column("classification", "Class at count"),
                 Column("phys_wh", "Physical WH", "qty"), Column("odoo_wh", "Odoo WH", "qty"),
                 Column("disc_wh", "Variance WH", "qty", True), Column("phys_prod", "Physical PROD", "qty"),
                 Column("odoo_prod", "Odoo Pre-Prod", "qty"), Column("disc_prod", "Variance PROD", "qty", True),
                 Column("abs_variance", "Abs. variance", "qty", True), Column("status", "Status"),
                 Column("review_status", "Review"), Column("counted_by", "Counted by"),
                 Column("snapshot_id", "Snapshot", "int")]


def _recon_rows(db: Session, recs: list[Reconciliation]) -> list[dict]:
    desc = dict(db.execute(select(Item.code, Item.description)).all())
    return [{"id": r.id, "count_date": r.count_date, "code": r.item_code, "description": desc.get(r.item_code, ""),
             "classification": r.classification_at_count, "phys_wh": r.phys_wh, "odoo_wh": r.odoo_wh,
             "disc_wh": r.disc_wh, "phys_prod": r.phys_prod, "odoo_prod": r.odoo_prod, "disc_prod": r.disc_prod,
             "abs_variance": abs(r.disc_wh or 0) + abs(r.disc_prod or 0), "net_variance": (r.disc_wh or 0) + (r.disc_prod or 0),
             "status": r.status, "review_status": r.review_status, "counted_by": r.counted_by,
             "snapshot_id": r.snapshot_id, "has_discrepancy": r.has_discrepancy} for r in recs]


# 4 ------------------------------------------------------------------------------------------
@register("reconciliation", 4, "Odoo vs Physical Reconciliation",
          "Physical vs Odoo per location for every reconciled count in the period (signed and absolute variance).",
          [FROM_F, TO_F, Q_F, CLASS_F,
           Filter("status", "Status", "select", _opts(["accurate", "discrepancy", "odoo_missing"]))])
def r_recon(db: Session, p: dict) -> ReportResult:
    start, end = _date_range(p)
    q = select(Reconciliation).where(Reconciliation.superseded.is_(False), Reconciliation.count_date >= start,
                                     Reconciliation.count_date <= end)
    if p.get("status"):
        q = q.where(Reconciliation.status == p["status"])
    if p.get("classification"):
        q = q.where(Reconciliation.classification_at_count == p["classification"])
    if p.get("q"):
        q = q.where(Reconciliation.item_code.ilike(f"%{p['q']}%"))
    rows = _recon_rows(db, list(db.scalars(q.order_by(Reconciliation.count_date.desc(), Reconciliation.item_code))))
    n_disc = sum(r["has_discrepancy"] for r in rows)
    return ReportResult("reconciliation", "Odoo vs Physical Inventory Reconciliation", RECON_COLUMNS, rows,
                        [("Reconciled counts", len(rows), "int"), ("With discrepancy", n_disc, "int"),
                         ("Discrepancy rate", n_disc / len(rows) if rows else None, "pct"),
                         ("Net variance", sum(r["net_variance"] for r in rows), "qty"),
                         ("Absolute variance", sum(r["abs_variance"] for r in rows), "qty")],
                        {"period": f"{start} – {end}", "note": "Variance = physical − Odoo. Quantity variance, not value."},
                        "/reconciliation/{id}")


# 5 ------------------------------------------------------------------------------------------
@register("discrepancies", 5, "Inventory Discrepancy Report",
          "Items whose latest count differs from Odoo, with variances, location, remarks and resolution status.",
          [Q_F, CLASS_F, SECTION_F, PLANT_F,
           Filter("review_status", "Review status", "select",
                  _opts(["open", "investigating", "recount_requested", "resolved"]))])
def r_disc(db: Session, p: dict) -> ReportResult:
    ds = inventory.build(db)
    rows = [r for r in inventory.apply_filters(ds.rows, p) if r.counted and r.has_discrepancy]
    if p.get("review_status"):
        rows = [r for r in rows if r.review_status == p["review_status"]]
    notes = {}
    for n in db.scalars(select(DiscrepancyNote).where(DiscrepancyNote.reconciliation_id.in_([r.recon_id for r in rows]))
                        .order_by(DiscrepancyNote.created_at)):
        notes[n.reconciliation_id] = n.note
    out = [{**r.as_dict(), "abs_variance": abs(r.disc_wh or 0) + abs(r.disc_prod or 0),
            "last_note": notes.get(r.recon_id)} for r in rows]
    cols = [Column("code", "RM Code"), Column("description", "Description"), Column("classification", "Class"),
            Column("plant_location", "Plant"), Column("last_count_date", "Last count", "date"),
            Column("phys_wh", "Physical WH", "qty"), Column("odoo_wh", "Odoo WH", "qty"),
            Column("disc_wh", "Variance WH", "qty", True), Column("phys_prod", "Physical PROD", "qty"),
            Column("odoo_prod", "Odoo Pre-Prod", "qty"), Column("disc_prod", "Variance PROD", "qty", True),
            Column("abs_variance", "Abs. variance", "qty", True), Column("review_status", "Resolution"),
            Column("last_note", "Latest note"), Column("remark", "Remark")]
    return ReportResult("discrepancies", "Inventory Discrepancy Report", cols, out,
                        [("Items with discrepancy", len(out), "int"),
                         ("Open", sum(r["review_status"] == "open" for r in out), "int"),
                         ("Resolved", sum(r["review_status"] == "resolved" for r in out), "int")],
                        _master_meta(ds, db, p), "/reconciliation/{recon_id}")


KPI_COLUMNS = [Column("classification", "Class"), Column("items", "# of items", "int", True),
               Column("counted", "# counted", "int", True), Column("remaining", "Remaining", "int", True),
               Column("discrepancies", "# of discrepancy", "int", True), Column("accurate", "Accurate", "int", True),
               Column("completion", "Count completion", "pct"),
               Column("accuracy", "Inventory accuracy % (count based)", "pct"),
               Column("overall_accuracy", "Overall accuracy", "pct"), Column("discrepancy_rate", "Discrepancy rate %", "pct")]


# 6 ------------------------------------------------------------------------------------------
@register("progress_overall", 6, "Overall Cycle Count Progress",
          "Legacy PROGRESS-overall: items, counted, discrepancies, completion, accuracy and discrepancy rate per class.",
          [SECTION_F, FAMILY_F, PLANT_F])
def r_overall(db: Session, p: dict) -> ReportResult:
    from ..engine import metrics
    ds = inventory.build(db)
    rows = inventory.apply_filters(ds.rows, p)
    k = inventory.overall_kpis(rows)
    out = [v.as_dict() for v in k.values()] + [metrics.total_of(k).as_dict()]
    return ReportResult("progress_overall", "Overall Cycle Count Progress", KPI_COLUMNS, out, [],
                        {**_master_meta(ds, db, p), "note": "# counted = items with at least one finalized count (all time)."})


# 7 ------------------------------------------------------------------------------------------
@register("progress_weekly", 7, "Weekly Cycle Count Progress",
          "Legacy PROGRESS-weekly: per class and Mon–Sun week, counted, discrepancies, accurate items, accuracy, cumulative completion.",
          [FROM_F, TO_F, CLASS_F])
def r_weekly(db: Session, p: dict) -> ReportResult:
    start, end = _date_range(p, 56)
    ds = inventory.build(db)
    blocks = inventory.weekly_kpis(db, ds.rows, start, end)
    rows = [w.as_dict() for c, ws in blocks.items() if not p.get("classification") or c == p["classification"] for w in ws]
    cols = [Column("classification", "Class"), Column("week_ending", "Date (week ending)", "date"),
            Column("week_label", "Week #"), Column("total_counted", "Total counted", "int", True),
            Column("discrepancy", "Discrepancy", "int", True), Column("accurate", "Accurate items", "int", True),
            Column("accuracy", "Accuracy %", "pct"), Column("cumulative_counted", "Cumulative counted", "int"),
            Column("completion", "Completion %", "pct")]
    return ReportResult("progress_weekly", "Weekly Cycle Count Progress", cols, rows, [],
                        {"period": f"{start} – {end}", "note": "Weeks run Monday–Sunday; week # = Excel WEEKNUM(date, 2)."})


def _run(db: Session, p: dict) -> AnalysisRun | None:
    if p.get("run_id"):
        return db.get(AnalysisRun, int(p["run_id"]))
    return analysis.current_run(db)


def _run_results(db: Session, p: dict, primary_only: bool) -> tuple[AnalysisRun | None, list[AnalysisResult]]:
    run = _run(db, p)
    if run is None:
        return None, []
    q = select(AnalysisResult).where(AnalysisResult.run_id == run.id)
    if primary_only:
        q = q.where(AnalysisResult.is_primary.is_(True))
    if p.get("abc_family"):
        q = q.where(AnalysisResult.family == p["abc_family"])
    if p.get("classification"):
        q = q.where(AnalysisResult.classification == p["classification"])
    if p.get("q"):
        q = q.where(AnalysisResult.item_code.ilike(f"%{p['q']}%"))
    return run, list(db.scalars(q.order_by(AnalysisResult.family, AnalysisResult.rank)))


def _run_meta(run: AnalysisRun | None) -> dict:
    if run is None:
        return {"note": "No analysis run yet."}
    return {"analysis_run_id": run.id, "run_status": run.status, "analysis_period": Period(run.period_start, run.months).label(),
            "rule_set_version": run.rule_set.version if run.rule_set else None, "run_source": run.source}


# 8 ------------------------------------------------------------------------------------------
@register("amc", 8, "AMC Report", "Monthly demand, AMC, observation period, latest stock count, stock in months and class.",
          [RUN_F, FAMILY_F, CLASS_F, Q_F])
def r_amc(db: Session, p: dict) -> ReportResult:
    run, res = _run_results(db, p, True)
    ds = {r.code: r for r in inventory.build(db).rows}
    months = Period(run.period_start, run.months).months if run else []
    cols = [Column("code", "RM Code"), Column("description", "Description"), Column("family", "Family")]
    cols += [Column(f"m{i}", f"{m:%b %y}", "qty") for i, m in enumerate(months)]
    cols += [Column("total", "Total", "qty", True), Column("frequency", "Months with demand", "int"),
             Column("amc", "AMC", "qty"), Column("phys_total", "Latest physical qty", "qty"),
             Column("stock_in_months", "Stock in months", "qty"), Column("classification", "Classification")]
    rows = []
    for r in res:
        m = ds.get(r.item_code)
        row = {"code": r.item_code, "description": m.description if m else "", "family": r.family, "total": r.total,
               "frequency": r.frequency, "amc": r.amc, "classification": r.classification,
               "phys_total": None if not m or not m.counted else (m.phys_wh or 0) + (m.phys_prod or 0),
               "stock_in_months": m.stock_in_months if m else None}
        for i, v in enumerate((r.monthly or [])[:len(months)]):
            row[f"m{i}"] = v
        rows.append(row)
    return ReportResult("amc", "AMC Report", cols, rows, [("Items", len(rows), "int")],
                        {**_run_meta(run), "note": "AMC = average of months with recorded demand (rule-set parameter amc.method)."},
                        "/items/{code}")


# 9 ------------------------------------------------------------------------------------------
@register("abc", 9, "ABC Analysis Report",
          "Per family: total demand, share, ranking, cumulative %, frequency %, quantity and frequency class, category.",
          [RUN_F, FAMILY_F, CLASS_F, Q_F])
def r_abc(db: Session, p: dict) -> ReportResult:
    run, res = _run_results(db, p, False)
    desc = dict(db.execute(select(Item.code, Item.description)).all())
    rows = [{"family": r.family, "rank": r.rank, "code": r.item_code, "description": desc.get(r.item_code, ""),
             "total": r.total, "share": r.share, "cum_items_pct": r.cum_items_pct, "cum_demand_pct": r.cum_demand_pct,
             "frequency": r.frequency, "frequency_pct": r.frequency_pct, "qty_class": r.qty_class,
             "freq_class": r.freq_class, "category": r.category, "declared_type": r.declared_type, "action": r.action,
             "classification": r.classification, "primary": r.is_primary} for r in res]
    cols = [Column("family", "Family"), Column("rank", "#", "int"), Column("code", "Code"),
            Column("description", "Description"), Column("total", "Total demand", "qty", True),
            Column("share", "Demand % of total", "pct"), Column("cum_items_pct", "Cumulative % of items", "pct"),
            Column("cum_demand_pct", "Cumulative % of demand", "pct"), Column("frequency", "Frequency", "int"),
            Column("frequency_pct", "Frequency %", "pct"), Column("qty_class", "Class (qty)"),
            Column("freq_class", "Class (freq)"), Column("category", "Category"), Column("declared_type", "Declared type"),
            Column("action", "Action"), Column("classification", "Classification")]
    cats = Counter(r["category"] for r in rows)
    return ReportResult("abc", "ABC Analysis Report", cols, rows,
                        [(f"Category {k}", v, "int") for k, v in sorted(cats.items())], _run_meta(run), "/items/{code}")


# 10 -----------------------------------------------------------------------------------------
@register("movement", 10, "Inventory Movement Classification",
          "Fast / Medium / Slow / Non-moving groups with classification basis and counting priority.",
          [CLASS_F, SECTION_F, FAMILY_F, PLANT_F])
def r_movement(db: Session, p: dict) -> ReportResult:
    ds = inventory.build(db)
    rows = inventory.apply_filters(ds.rows, p)
    out = [{"classification": r.classification, "code": r.code, "description": r.description, "category": r.category,
            "frequency": r.frequency, "total_demand": r.total_demand, "amc": r.amc, "action": r.action,
            "interval_days": r.interval_days, "priority": cls_mod.action_priority(r.action) + 1,
            "next_due": r.next_due, "due_status": r.due_status} for r in rows]
    order = {c: i for i, c in enumerate(cls_mod.MOVEMENT_CLASSES)}
    out.sort(key=lambda r: (order.get(r["classification"], 9), r["code"]))
    cnt = Counter(r["classification"] for r in out)
    cols = [Column("classification", "Classification"), Column("code", "RM Code"), Column("description", "Description"),
            Column("category", "Category"), Column("frequency", "Months with demand", "int"),
            Column("total_demand", "Total demand", "qty"), Column("amc", "AMC", "qty"), Column("action", "Action"),
            Column("interval_days", "Interval", "int"), Column("priority", "Priority", "int"),
            Column("next_due", "Next count", "date"), Column("due_status", "Schedule")]
    return ReportResult("movement", "Inventory Movement Classification", cols, out,
                        [(c, cnt.get(c, 0), "int") for c in cls_mod.MOVEMENT_CLASSES],
                        {**_master_meta(ds, db, p), "note": "Non Moving = no demand recorded in any month of the period; "
                                                           "other classes come from the category matrix."}, "/items/{code}")


# 11 -----------------------------------------------------------------------------------------
@register("schedule", 11, "Cycle Count Schedule & Overdue",
          "Last count, interval, next count, overdue days, priority, plant, assignment and status.",
          [Filter("due_status", "Schedule", "select", _opts(["overdue", "due_today", "upcoming", "scheduled", "unscheduled"])),
           CLASS_F, ACTION_F, PLANT_F, SECTION_F, Q_F])
def r_schedule(db: Session, p: dict) -> ReportResult:
    ds = inventory.build(db)
    rows = inventory.apply_filters(ds.rows, p)
    assigned = {}
    for pi, plan in db.execute(select(CountPlanItem, CountPlan).join(CountPlan).where(
            CountPlan.status == "open", CountPlanItem.status == "pending")).all():
        assigned[pi.item_code] = (plan.id, pi.assigned_to_id)
    names = dict(db.execute(select(User.id, User.name)).all())
    rows.sort(key=lambda r: (r.next_due or date.max, cls_mod.action_priority(r.action), r.code))
    out = [{"code": r.code, "description": r.description, "action": r.action, "classification": r.classification,
            "plant_location": r.plant_location, "last_count_date": r.last_count_date, "interval_days": r.interval_days,
            "next_due": r.next_due, "overdue_days": r.overdue_days, "due_status": r.due_status,
            "priority": cls_mod.action_priority(r.action) + 1,
            "plan_id": assigned.get(r.code, (None, None))[0],
            "assigned_to": names.get(assigned.get(r.code, (None, None))[1])} for r in rows]
    st = Counter(r["due_status"] for r in out)
    cols = [Column("code", "RM Code"), Column("description", "Description"), Column("action", "Action"),
            Column("classification", "Class"), Column("plant_location", "Plant"),
            Column("last_count_date", "Last count", "date"), Column("interval_days", "Interval", "int"),
            Column("next_due", "Next count", "date"), Column("overdue_days", "Overdue days", "int"),
            Column("due_status", "Status"), Column("priority", "Priority", "int"), Column("plan_id", "Open plan", "int"),
            Column("assigned_to", "Assigned to")]
    return ReportResult("schedule", "Cycle Count Schedule and Overdue Report", cols, out,
                        [(k.replace("_", " ").title(), st.get(k, 0), "int")
                         for k in ("overdue", "due_today", "upcoming", "scheduled", "unscheduled")],
                        {**_master_meta(ds, db, p), "never_counted_anchor": ds.anchor}, "/items/{code}")


# 12 -----------------------------------------------------------------------------------------
@register("accuracy_trend", 12, "Inventory Accuracy & Variance Trends",
          "Weekly counted items, discrepancies, item accuracy and quantity variance (from stored reconciliations).",
          [FROM_F, TO_F, CLASS_F])
def r_trend(db: Session, p: dict) -> ReportResult:
    from ..engine import metrics
    start, end = _date_range(p, 182)
    q = select(Reconciliation).where(Reconciliation.superseded.is_(False), Reconciliation.count_date >= start,
                                     Reconciliation.count_date <= end)
    if p.get("classification"):
        q = q.where(Reconciliation.classification_at_count == p["classification"])
    weeks: dict[date, dict] = {}
    we = metrics.week_end(start)
    while we <= metrics.week_end(end):
        weeks[we] = {"week_ending": we, "week_label": f"WK#{metrics.excel_weeknum_monday(we)}", "counted": 0,
                     "discrepancies": 0, "net_variance": 0.0, "abs_variance": 0.0}
        we += timedelta(days=7)
    for r in db.scalars(q):
        w = weeks[metrics.week_end(r.count_date)]
        w["counted"] += 1
        w["discrepancies"] += int(r.has_discrepancy)
        w["net_variance"] += (r.disc_wh or 0) + (r.disc_prod or 0)
        w["abs_variance"] += abs(r.disc_wh or 0) + abs(r.disc_prod or 0)
    rows = list(weeks.values())
    for w in rows:
        w["accuracy"] = metrics.ratio(w["counted"] - w["discrepancies"], w["counted"])
        w["discrepancy_rate"] = metrics.ratio(w["discrepancies"], w["counted"])
    cols = [Column("week_ending", "Week ending", "date"), Column("week_label", "Week #"),
            Column("counted", "Counted", "int", True), Column("discrepancies", "Discrepancies", "int", True),
            Column("accuracy", "Accuracy %", "pct"), Column("discrepancy_rate", "Discrepancy rate", "pct"),
            Column("net_variance", "Net qty variance", "qty", True), Column("abs_variance", "Abs. qty variance", "qty", True)]
    return ReportResult("accuracy_trend", "Inventory Accuracy and Variance Trends", cols, rows, [],
                        {"period": f"{start} – {end}", "note": "Item-count accuracy and quantity variance only; "
                                                              "no financial valuation is applied."})


# 13 -----------------------------------------------------------------------------------------
@register("data_quality", 13, "Data Quality & Unmatched Inventory",
          "Duplicate codes, missing products/UoM, unmapped locations, unknown counted codes, negative Odoo stock, …",
          [Filter("kind", "Kind", "select", lambda db: sorted(dq.KINDS)),
           Filter("status", "Status", "select", _opts(["open", "resolved", "ignored"]))])
def r_dq(db: Session, p: dict) -> ReportResult:
    q = select(DqException)
    if p.get("kind"):
        q = q.where(DqException.kind == p["kind"])
    q = q.where(DqException.status == (p.get("status") or "open"))
    rows = [{"id": e.id, "kind": e.kind, "description": dq.KINDS.get(e.kind, ""), "ref": e.ref, "detail": e.detail,
             "severity": e.severity, "status": e.status, "source": e.source, "first_seen_at": e.first_seen_at,
             "last_seen_at": e.last_seen_at}
            for e in db.scalars(q.order_by(DqException.severity, DqException.kind, DqException.ref))]
    cnt = Counter(r["kind"] for r in rows)
    cols = [Column("kind", "Kind"), Column("ref", "Reference"), Column("detail", "Detail"), Column("severity", "Severity"),
            Column("status", "Status"), Column("source", "Source"), Column("first_seen_at", "First seen", "datetime"),
            Column("last_seen_at", "Last seen", "datetime")]
    return ReportResult("data_quality", "Data Quality and Unmatched Inventory", cols, rows,
                        [(k, v, "int") for k, v in sorted(cnt.items())])


# 14 -----------------------------------------------------------------------------------------
@register("sync_history", 14, "Odoo Synchronisation History",
          "Sync and import runs: time, scope, records, failures, snapshot ids and stale-data condition.",
          [FROM_F, TO_F, Filter("status", "Status", "select", _opts(["success", "failed", "running"])),
           Filter("kind", "Kind", "select", _opts(["inventory", "demand", "import"]))])
def r_sync(db: Session, p: dict) -> ReportResult:
    start, end = _date_range(p, 30)
    q = select(SyncRun).where(SyncRun.started_at >= datetime.combine(start, datetime.min.time()),
                              SyncRun.started_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    if p.get("status"):
        q = q.where(SyncRun.status == p["status"])
    if p.get("kind"):
        q = q.where(SyncRun.kind == p["kind"])
    rows = [{"id": r.id, "kind": r.kind, "mode": r.mode, "status": r.status, "started_at": r.started_at,
             "finished_at": r.finished_at, "records": r.stats.get("products") or r.stats.get("moves") or r.stats.get("entries"),
             "quants": r.stats.get("quants"), "snapshot_id": r.stats.get("snapshot_id"),
             "unmapped": r.stats.get("quants_unmapped_location"), "scope": ", ".join(f"{k}={v}" for k, v in r.scope.items()),
             "error": r.error} for r in db.scalars(q.order_by(SyncRun.started_at.desc()))]
    st = sync.staleness(db, sync.latest_snapshot(db))
    cols = [Column("id", "Run", "int"), Column("kind", "Kind"), Column("mode", "Mode"), Column("status", "Status"),
            Column("started_at", "Started", "datetime"), Column("finished_at", "Finished", "datetime"),
            Column("records", "Records", "int"), Column("quants", "Quants", "int"), Column("snapshot_id", "Snapshot", "int"),
            Column("unmapped", "Quants in unmapped locations", "int"), Column("scope", "Scope"), Column("error", "Error")]
    return ReportResult("sync_history", "Odoo Synchronisation History", cols, rows,
                        [("Runs", len(rows), "int"), ("Failed", sum(r["status"] == "failed" for r in rows), "int"),
                         ("Latest snapshot stale", "yes" if st["stale"] else "no", "text")],
                        {"period": f"{start} – {end}"})


# 15 -----------------------------------------------------------------------------------------
@register("audit_trail", 15, "Inventory Audit Trail",
          "Count creation and corrections, reviews, configuration changes, syncs, imports, logins and report exports.",
          [FROM_F, TO_F, Filter("action", "Action contains"), Filter("user", "User login contains"),
           Filter("entity", "Entity", "select", _opts(["count_session", "count_entry", "reconciliation", "item", "rule_set",
                                                      "app_setting", "stock_location", "sync_run", "analysis_run",
                                                      "app_user", "report_run", "count_plan", "dq_exception"]))])
def r_audit(db: Session, p: dict) -> ReportResult:
    start, end = _date_range(p, 30)
    q = select(AuditLog).where(AuditLog.at >= datetime.combine(start, datetime.min.time()),
                               AuditLog.at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    if p.get("action"):
        q = q.where(AuditLog.action.ilike(f"%{p['action']}%"))
    if p.get("user"):
        q = q.where(AuditLog.user_login.ilike(f"%{p['user']}%"))
    if p.get("entity"):
        q = q.where(AuditLog.entity == p["entity"])
    rows = [{"at": a.at, "user": a.user_login, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
             "detail": _short(a.detail), "ip": a.ip} for a in db.scalars(q.order_by(AuditLog.at.desc()).limit(5000))]
    cols = [Column("at", "Time", "datetime"), Column("user", "User"), Column("action", "Action"), Column("entity", "Entity"),
            Column("entity_id", "Id"), Column("detail", "Detail"), Column("ip", "IP")]
    return ReportResult("audit_trail", "Inventory Audit Trail", cols, rows, [("Events (max 5,000)", len(rows), "int")],
                        {"period": f"{start} – {end}"})


def _short(d: dict) -> str:
    s = ", ".join(f"{k}={v}" for k, v in (d or {}).items())
    return s if len(s) <= 300 else s[:297] + "…"


# 16 -----------------------------------------------------------------------------------------
CUSTOM_FIELDS = {c.key: c for c in MASTER_COLUMNS}


@register("custom", 16, "Custom Filtered Inventory Report",
          "Choose masterlist fields, filter, sort and group, then export. Source data is never changed.",
          [Q_F, CLASS_F, ACTION_F, SECTION_F, FAMILY_F, PLANT_F,
           Filter("counted", "Counted", "select", _opts(["yes", "no"])),
           Filter("discrepancy", "Discrepancy", "select", _opts(["yes", "no"])),
           Filter("fields", "Fields (comma separated keys)"),
           Filter("sort", "Sort by field", "select", lambda db: list(CUSTOM_FIELDS)),
           Filter("group", "Group by field", "select", lambda db: ["classification", "action", "material_section",
                                                                    "abc_family", "plant_location", "due_status",
                                                                    "recon_status"])])
def r_custom(db: Session, p: dict) -> ReportResult:
    ds = inventory.build(db)
    rows = [r.as_dict() for r in inventory.apply_filters(ds.rows, p)]
    keys = [k.strip() for k in (p.get("fields") or "code,description,classification,action,next_due").split(",")
            if k.strip() in CUSTOM_FIELDS]
    group = p.get("group") if p.get("group") in CUSTOM_FIELDS else None
    if group and group not in keys:
        keys.insert(0, group)
    sort = p.get("sort") if p.get("sort") in CUSTOM_FIELDS else "code"
    rows.sort(key=lambda r: ((r.get(group) or "") if group else "", r.get(sort) is None, r.get(sort) or 0
                             if CUSTOM_FIELDS[sort].kind in ("qty", "int") else str(r.get(sort) or "")))
    summary = [(f"{group}: {k or '(blank)'}", v, "int") for k, v in sorted(Counter(r.get(group) for r in rows).items(),
                                                                          key=lambda kv: str(kv[0]))] if group else []
    return ReportResult("custom", "Custom Filtered Inventory Report", [CUSTOM_FIELDS[k] for k in keys],
                        [{k: r.get(k) for k in keys} | {"code": r["code"]} for r in rows],
                        [("Rows", len(rows), "int")] + summary,
                        {**_master_meta(ds, db, p), "available_fields": ", ".join(CUSTOM_FIELDS)}, "/items/{code}")


def run(db: Session, key: str, params: dict) -> ReportResult:
    if key not in REGISTRY:
        raise KeyError(key)
    res = REGISTRY[key].build(db, params)
    res.meta.setdefault("generated_at", datetime.now().astimezone())
    res.meta.setdefault("report_number", REGISTRY[key].number)
    return res


__all__ = ["REGISTRY", "run", "ReportResult", "Column", "add_months"]
