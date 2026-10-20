"""AMC / ABC / movement-classification analysis runs (Task.md §13, §14; BR-01..BR-13).

A run is computed from one demand batch, one period and one rule set, and stored in full
(per item and family) so any past report can be reproduced. Only an *approved* run drives the
masterlist, schedule and dashboards; approving supersedes the previous approved run.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine import abc, classification
from ..engine import amc as amc_mod
from ..engine.amc import Period
from ..models import AnalysisResult, AnalysisRun, DemandBatch, DemandLine, Item, ItemFamily, RuleSet, User, utcnow
from . import audit, rules


def demand_by_item(db: Session, batch_id: int) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = defaultdict(dict)
    for ln in db.scalars(select(DemandLine).where(DemandLine.batch_id == batch_id)):
        out[ln.item_code][ln.month] = ln.qty
    return out


def family_members(db: Session) -> dict[str, list[str]]:
    """Family → item codes: imported memberships plus each tracked item's primary family."""
    fams: dict[str, list[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for f in db.scalars(select(ItemFamily).order_by(ItemFamily.id)):
        fams[f.family].append(f.item_code)
        seen.add((f.family, f.item_code))
    for it in db.scalars(select(Item).where(Item.tracked.is_(True), Item.abc_family.isnot(None)).order_by(Item.code)):
        if (it.abc_family, it.code) not in seen:
            fams[it.abc_family].append(it.code)
    return fams


def run_analysis(db: Session, user: User | None, batch_id: int, period: Period, rule_set: RuleSet | None = None,
                 notes: str | None = None) -> AnalysisRun:
    batch = db.get(DemandBatch, batch_id)
    if batch is None:
        raise LookupError("demand batch not found")
    rs = rule_set or rules.active_rule_set(db)
    params = rules.params_of(rs)
    abc_params = abc.AbcParams.from_dict(params["abc"])
    amc_method = params["amc"]["method"]
    demand = demand_by_item(db, batch_id)
    fams = family_members(db)
    primary = {i.code: i.abc_family for i in db.scalars(select(Item).where(Item.abc_family.isnot(None)))}
    run = AnalysisRun(source="engine", period_start=period.start, months=period.months_count, demand_batch_id=batch_id,
                      rule_set_id=rs.id, status="draft", notes=notes, created_by_id=user.id if user else None)
    db.add(run)
    db.flush()
    by_class, unknown_cat = Counter(), 0
    results = []
    for family, codes in sorted(fams.items()):
        inputs = [abc.AbcInput(c, amc_mod.monthly_series(demand.get(c, {}), period)) for c in dict.fromkeys(codes)]
        for r in abc.analyse_family(inputs, period.months_count, abc_params):
            cl = classification.classify(r.category, r.frequency, rs.class_matrix)
            if not cl.found:
                unknown_cat += 1
            is_primary = primary.get(r.code, family) == family
            results.append(AnalysisResult(
                run_id=run.id, item_code=r.code, family=family, is_primary=is_primary, monthly=r.series,
                total=r.total, share=r.share, frequency=r.frequency, frequency_pct=r.frequency_pct, rank=r.rank,
                cum_items_pct=r.cum_items_pct, cum_demand_pct=r.cum_demand_pct, qty_class=r.qty_class,
                freq_class=r.freq_class, category=r.category, declared_type=cl.declared_type, action=cl.action,
                classification=cl.classification, interval_days=cl.interval_days,
                amc=amc_mod.amc(r.series, amc_method)))
            if is_primary:
                by_class[cl.classification] += 1
    db.add_all(results)
    in_family = {c for codes in fams.values() for c in codes}
    run.stats = {"families": len(fams), "results": len(results), "by_class": dict(by_class),
                 "unknown_categories": unknown_cat, "period": period.label(),
                 "demand_items_without_family": sum(1 for c in demand if c not in in_family),
                 "rule_set_version": rs.version}
    audit.record(db, user, "analysis.run", "analysis_run", run.id, run.stats)
    return run


def approve(db: Session, user: User, run_id: int) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise LookupError("analysis run not found")
    if run.status != "draft":
        raise ValueError(f"only draft runs can be approved (run is {run.status})")
    for prev in db.scalars(select(AnalysisRun).where(AnalysisRun.status == "approved")):
        prev.status = "superseded"
    run.status, run.approved_at, run.approved_by_id = "approved", utcnow(), user.id
    audit.record(db, user, "analysis.approve", "analysis_run", run.id, {"period_start": run.period_start})
    return run


def reject(db: Session, user: User, run_id: int, note: str) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None or run.status != "draft":
        raise ValueError("only draft runs can be rejected")
    run.status = "rejected"
    audit.record(db, user, "analysis.reject", "analysis_run", run.id, {"note": note})
    return run


def current_run(db: Session) -> AnalysisRun | None:
    return db.scalars(select(AnalysisRun).where(AnalysisRun.status == "approved")
                      .order_by(AnalysisRun.approved_at.desc(), AnalysisRun.id.desc())).first()


def primary_results(db: Session, run_id: int | None) -> dict[str, AnalysisResult]:
    if run_id is None:
        return {}
    out: dict[str, AnalysisResult] = {}
    for r in db.scalars(select(AnalysisResult).where(AnalysisResult.run_id == run_id)
                        .order_by(AnalysisResult.is_primary.desc(), AnalysisResult.id)):
        out.setdefault(r.item_code, r)
    return out


def compare(db: Session, run_a: int, run_b: int) -> list[dict]:
    """Item-level differences between two runs (primary family results)."""
    a, b = primary_results(db, run_a), primary_results(db, run_b)
    out = []
    for code in sorted(set(a) | set(b)):
        ra, rb = a.get(code), b.get(code)
        fa = (ra.category, ra.classification, ra.action, ra.interval_days) if ra else None
        fb = (rb.category, rb.classification, rb.action, rb.interval_days) if rb else None
        if fa != fb or (ra and rb and abs(ra.amc - rb.amc) > 1e-9):
            out.append({"code": code, "family": (rb or ra).family,
                        "category_a": ra.category if ra else None, "category_b": rb.category if rb else None,
                        "class_a": ra.classification if ra else None, "class_b": rb.classification if rb else None,
                        "action_a": ra.action if ra else None, "action_b": rb.action if rb else None,
                        "interval_a": ra.interval_days if ra else None, "interval_b": rb.interval_days if rb else None,
                        "amc_a": ra.amc if ra else None, "amc_b": rb.amc if rb else None})
    return out
