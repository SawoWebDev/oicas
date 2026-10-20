"""The Inventory Masterlist dataset (legacy W2 ``Master``) and everything derived from it.

``build`` is the single place where item attributes, the approved analysis run, the latest
reconciliation and the schedule are joined. Dashboard, masterlist screen, schedule, progress
metrics and exports all call it, so they always agree.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine import amc as amc_mod
from ..engine import metrics, scheduling
from ..models import Item, Reconciliation, User
from . import analysis, audit, counting, rules


@dataclass
class MasterRow:
    code: str
    description: str
    uom: str | None
    abc_family: str | None
    material_section: str | None
    plant_location: str | None
    remark: str | None
    is_jit: bool
    odoo_product_id: int | None
    # analysis (approved run)
    category: str | None = None
    declared_type: str | None = None
    action: str | None = None
    classification: str | None = None
    amc: float | None = None
    interval_days: int | None = None
    total_demand: float | None = None
    frequency: int | None = None
    # latest count / reconciliation
    last_count_date: date | None = None
    counted_by: str | None = None
    phys_wh: float | None = None
    phys_prod: float | None = None
    odoo_wh: float | None = None
    odoo_prod: float | None = None
    disc_wh: float | None = None
    disc_prod: float | None = None
    has_discrepancy: bool = False
    recon_status: str = "not_counted"
    review_status: str | None = None
    recon_id: int | None = None
    snapshot_id: int | None = None
    # derived
    stock_in_months: float | None = None
    next_due: date | None = None
    due_status: str = scheduling.UNSCHEDULED
    overdue_days: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def counted(self) -> bool:
        return self.last_count_date is not None

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("extra")
        return d


@dataclass
class Dataset:
    rows: list[MasterRow]
    as_of: date
    run_id: int | None
    run_period: str | None
    rule_set_version: int | None
    anchor: date | None


def build(db: Session, as_of: date | None = None, include_untracked: bool = False) -> Dataset:
    as_of = as_of or date.today()
    run = analysis.current_run(db)
    results = analysis.primary_results(db, run.id) if run else {}
    recons = counting.current_reconciliations(db)
    rs = rules.active_rule_set(db, as_of)
    sch = rules.params_of(rs)["schedule"]
    anchor = (run.approved_at.date() if run and run.approved_at else None) or as_of
    q = select(Item)
    if not include_untracked:
        q = q.where(Item.tracked.is_(True))
    rows = []
    for it in db.scalars(q.order_by(Item.code)):
        r = MasterRow(code=it.code, description=it.description, uom=it.uom_name, abc_family=it.abc_family,
                      material_section=it.material_section, plant_location=it.plant_location, remark=it.remark,
                      is_jit=it.is_jit, odoo_product_id=it.odoo_product_id)
        a = results.get(it.code)
        if a is not None:
            r.category, r.declared_type, r.action, r.classification = a.category, a.declared_type, a.action, a.classification
            r.amc, r.interval_days, r.total_demand, r.frequency = a.amc, a.interval_days, a.total, a.frequency
        rc: Reconciliation | None = recons.get(it.code)
        if rc is not None:
            r.last_count_date, r.counted_by, r.recon_id, r.snapshot_id = rc.count_date, rc.counted_by, rc.id, rc.snapshot_id
            r.phys_wh, r.phys_prod, r.odoo_wh, r.odoo_prod = rc.phys_wh, rc.phys_prod, rc.odoo_wh, rc.odoo_prod
            r.disc_wh, r.disc_prod, r.has_discrepancy = rc.disc_wh, rc.disc_prod, rc.has_discrepancy
            r.recon_status, r.review_status = rc.status, rc.review_status
        r.stock_in_months = amc_mod.stock_in_months(r.phys_wh, r.phys_prod, r.amc)
        r.next_due = scheduling.next_due(r.last_count_date, r.interval_days, sch["never_counted"], anchor)
        r.due_status = scheduling.due_status(r.next_due, as_of, int(sch["upcoming_days"]))
        r.overdue_days = scheduling.overdue_days(r.next_due, as_of)
        rows.append(r)
    return Dataset(rows, as_of, run.id if run else None,
                   amc_mod.Period(run.period_start, run.months).label() if run else None, rs.version, anchor)


# ------------------------------------------------------------------ filters
FILTERS = ("q", "classification", "action", "material_section", "abc_family", "plant_location", "due_status",
           "recon_status", "review_status", "counted", "discrepancy")


def apply_filters(rows: list[MasterRow], f: dict) -> list[MasterRow]:
    out = rows
    if f.get("q"):
        needle = f["q"].strip().casefold()
        out = [r for r in out if needle in r.code.casefold() or needle in (r.description or "").casefold()]
    for key in ("classification", "action", "material_section", "abc_family", "plant_location", "due_status",
                "recon_status", "review_status"):
        if f.get(key):
            out = [r for r in out if (getattr(r, key) or "") == f[key]]
    if f.get("counted") in ("yes", "no"):
        want = f["counted"] == "yes"
        out = [r for r in out if r.counted == want]
    if f.get("discrepancy") in ("yes", "no"):
        want = f["discrepancy"] == "yes"
        out = [r for r in out if r.counted and r.has_discrepancy == want]
    return out


# ------------------------------------------------------------------ metrics (F-24 / F-25)
def overall_kpis(rows: list[MasterRow]) -> dict[str, metrics.OverallKpi]:
    return metrics.overall(metrics.ItemProgress(r.code, r.classification, r.counted, r.has_discrepancy) for r in rows)


def weekly_kpis(db: Session, rows: list[MasterRow], start: date, end: date) -> dict[str, list[metrics.WeeklyRow]]:
    items_per_class = {k: v.items for k, v in overall_kpis(rows).items()}
    tracked = {r.code for r in rows}
    events = [metrics.CountEvent(rc.item_code, rc.count_date, rc.classification_at_count, rc.has_discrepancy)
              for rc in db.scalars(select(Reconciliation).where(Reconciliation.superseded.is_(False),
                                                                Reconciliation.count_date >= start,
                                                                Reconciliation.count_date <= end))
              if rc.item_code in tracked]
    return metrics.weekly(events, items_per_class, start, end)


# ------------------------------------------------------------------ app-owned item attributes
EDITABLE = ("material_section", "abc_family", "plant_location", "remark", "is_jit", "tracked")


def update_item(db: Session, user: User, code: str, values: dict) -> Item:
    it = db.scalars(select(Item).where(Item.code == code)).first()
    if it is None:
        raise LookupError("item not found")
    before, after = {}, {}
    plants = [str(p) for p in rules.get_setting(db, "plant_locations")]
    for k, v in values.items():
        if k not in EDITABLE:
            raise ValueError(f"{k} is owned by Odoo or calculated and can't be edited")
        if k in ("is_jit", "tracked"):
            v = bool(v)
        elif isinstance(v, str):
            v = v.strip() or None
        if k == "plant_location" and v and v not in plants:
            raise ValueError(f"plant location must be one of {', '.join(plants)}")
        if k == "abc_family" and v and v not in rules.get_setting(db, "abc_families"):
            raise ValueError("unknown ABC family")
        if getattr(it, k) != v:
            before[k], after[k] = getattr(it, k), v
            setattr(it, k, v)
    if after:
        audit.record(db, user, "item.update", "item", code, {"before": before, "after": after})
    return it
