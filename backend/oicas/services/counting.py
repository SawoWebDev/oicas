"""Count plans, count sessions/entries and reconciliation (Task.md §11, §12; BR-14..BR-18, BR-22..BR-25).

Lifecycle: draft → submitted → finalized (or cancelled). Entries can be added/removed only in
draft. After submission an entry can only be *corrected*: a new entry supersedes it with a
reason. Finalizing links the session to an Odoo snapshot and (re)computes reconciliations.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine import reconciliation as recon_engine
from ..models import (CountEntry, CountPlan, CountPlanItem, CountSession, DiscrepancyNote, InventorySnapshot, Item,
                      Reconciliation, User, utcnow)
from . import analysis, audit, rules, sync


class CountError(ValueError):
    pass


class StaleSnapshotError(CountError):
    pass


# ------------------------------------------------------------------ plans
def create_plan(db: Session, user: User, name: str, plan_date: date, due_date: date | None,
                items: list[tuple[str, str, int]], assignee_id: int | None = None, notes: str | None = None) -> CountPlan:
    """``items`` = [(item_code, reason, priority)]."""
    if not items:
        raise CountError("a count plan needs at least one item")
    plan = CountPlan(name=name.strip() or f"Count plan {plan_date}", plan_date=plan_date, due_date=due_date,
                     notes=notes, created_by_id=user.id)
    db.add(plan)
    seen = set()
    for code, reason, prio in items:
        if code in seen:
            continue
        seen.add(code)
        plan.items.append(CountPlanItem(item_code=code, reason=reason, priority=prio, assigned_to_id=assignee_id))
    db.flush()
    audit.record(db, user, "plan.create", "count_plan", plan.id, {"items": len(seen), "plan_date": plan_date})
    return plan


def assign_plan_items(db: Session, user: User, plan_id: int, item_ids: list[int], assignee_id: int | None) -> int:
    n = 0
    for pi in db.scalars(select(CountPlanItem).where(CountPlanItem.plan_id == plan_id, CountPlanItem.id.in_(item_ids))):
        pi.assigned_to_id = assignee_id
        n += 1
    audit.record(db, user, "plan.assign", "count_plan", plan_id, {"items": n, "assignee_id": assignee_id})
    return n


def set_plan_status(db: Session, user: User, plan_id: int, status: str) -> CountPlan:
    if status not in ("open", "closed", "cancelled"):
        raise CountError("invalid plan status")
    plan = db.get(CountPlan, plan_id)
    if plan is None:
        raise CountError("plan not found")
    plan.status = status
    audit.record(db, user, "plan.status", "count_plan", plan_id, {"status": status})
    return plan


# ------------------------------------------------------------------ sessions & entries
def create_session(db: Session, user: User, count_date: date, counted_by_name: str, plan_id: int | None = None,
                   client_token: str | None = None, remarks: str | None = None, source: str = "app",
                   recount_of: int | None = None) -> CountSession:
    if client_token:
        existing = db.scalars(select(CountSession).where(CountSession.client_token == client_token)).first()
        if existing is not None:
            return existing  # idempotent: double-submitted form creates nothing new
    if count_date > date.today():
        raise CountError("count date cannot be in the future")
    if not (counted_by_name or "").strip():
        raise CountError("enter who counted")
    s = CountSession(count_date=count_date, counted_by_name=counted_by_name.strip(), counter_user_id=user.id,
                     plan_id=plan_id, client_token=client_token, remarks=remarks, source=source,
                     created_by_id=user.id, recount_of_reconciliation_id=recount_of)
    db.add(s)
    db.flush()
    audit.record(db, user, "count.session.create", "count_session", s.id,
                 {"count_date": count_date, "counted_by": counted_by_name, "plan_id": plan_id, "recount_of": recount_of})
    return s


def _session(db: Session, session_id: int) -> CountSession:
    s = db.get(CountSession, session_id)
    if s is None:
        raise CountError("count session not found")
    return s


def _validate_entry(db: Session, item_code: str, bucket: str, slot: str, qty: float) -> Item:
    item = db.scalars(select(Item).where(Item.code == item_code)).first()
    if item is None:
        raise CountError(f"unknown item code {item_code!r}")
    if bucket not in recon_engine.BUCKETS:
        raise CountError("location must be WAREHOUSE or PRODUCTION")
    if str(slot) not in [str(x) for x in rules.get_setting(db, "count_slots")]:
        raise CountError(f"invalid count slot {slot!r}")
    if qty is None or qty < 0:
        raise CountError("quantity must be zero or positive")
    return item


def add_entry(db: Session, user: User, session_id: int, item_code: str, bucket: str, qty: float, slot: str = "1",
              round_no: int = 1, remarks: str | None = None) -> CountEntry:
    s = _session(db, session_id)
    if s.status != "draft":
        raise CountError("entries can only be added while the session is a draft; use a correction instead")
    item = _validate_entry(db, item_code.strip(), bucket, slot, qty)
    e = CountEntry(session_id=s.id, item_code=item.code, bucket=bucket, slot=str(slot), round=round_no,
                   qty=float(qty), uom_name=item.uom_name, remarks=remarks, created_by_id=user.id)
    db.add(e)
    db.flush()
    audit.record(db, user, "count.entry.add", "count_entry", e.id,
                 {"session_id": s.id, "item": item.code, "bucket": bucket, "slot": slot, "qty": qty})
    return e


def remove_draft_entry(db: Session, user: User, entry_id: int) -> None:
    e = db.get(CountEntry, entry_id)
    if e is None:
        raise CountError("entry not found")
    if e.session.status != "draft":
        raise CountError("submitted entries cannot be removed; use a correction")
    audit.record(db, user, "count.entry.remove", "count_entry", e.id,
                 {"session_id": e.session_id, "item": e.item_code, "qty": e.qty})
    db.delete(e)


def submit(db: Session, user: User, session_id: int) -> CountSession:
    s = _session(db, session_id)
    if s.status != "draft":
        raise CountError(f"session is {s.status}, not draft")
    if not s.entries:
        raise CountError("add at least one count entry before submitting")
    s.status, s.submitted_at = "submitted", utcnow()
    audit.record(db, user, "count.session.submit", "count_session", s.id, {"entries": len(s.entries)})
    return s


def cancel(db: Session, user: User, session_id: int, reason: str) -> CountSession:
    s = _session(db, session_id)
    if s.status not in ("draft", "submitted"):
        raise CountError("only draft or submitted sessions can be cancelled")
    if not reason.strip():
        raise CountError("a cancellation reason is required")
    s.status = "cancelled"
    audit.record(db, user, "count.session.cancel", "count_session", s.id, {"reason": reason})
    return s


def correct_entry(db: Session, user: User, entry_id: int, new_qty: float, reason: str) -> CountEntry:
    old = db.get(CountEntry, entry_id)
    if old is None:
        raise CountError("entry not found")
    if old.superseded_by_id is not None:
        raise CountError("this entry was already corrected; correct the latest version")
    if old.session.status not in ("submitted", "finalized"):
        raise CountError("draft entries are edited by removing and re-adding them")
    if not (reason or "").strip():
        raise CountError("a correction reason is required")
    _validate_entry(db, old.item_code, old.bucket, old.slot, new_qty)
    new = CountEntry(session_id=old.session_id, item_code=old.item_code, bucket=old.bucket, slot=old.slot,
                     round=old.round, qty=float(new_qty), uom_name=old.uom_name, remarks=old.remarks,
                     created_by_id=user.id, correction_reason=reason.strip())
    db.add(new)
    db.flush()
    old.superseded_by_id, old.superseded_at = new.id, utcnow()
    audit.record(db, user, "count.entry.correct", "count_entry", old.id,
                 {"new_entry_id": new.id, "before": old.qty, "after": new_qty, "reason": reason})
    if old.session.status == "finalized":
        recompute(db, old.item_code, old.session.count_date)
    return new


def finalize(db: Session, user: User, session_id: int, snapshot_id: int | None = None,
             allow_stale: bool = False) -> CountSession:
    s = _session(db, session_id)
    if s.status != "submitted":
        raise CountError(f"session is {s.status}; submit it before finalizing")
    snap = db.get(InventorySnapshot, snapshot_id) if snapshot_id else sync.latest_snapshot(db)
    if snap is None:
        raise StaleSnapshotError("no Odoo snapshot available; run an Odoo sync first")
    st = sync.staleness(db, snap)
    if snap.source == "odoo" and st["stale"] and not allow_stale:
        raise StaleSnapshotError(f"the latest Odoo snapshot is {st['age_hours']:.1f} h old (limit "
                                 f"{st['threshold_hours']:.0f} h); sync Odoo or confirm finalizing against stale data")
    s.status, s.finalized_at, s.finalized_by_id, s.snapshot_id = "finalized", utcnow(), user.id, snap.id
    codes = sorted({e.item_code for e in s.entries if e.superseded_by_id is None})
    if s.recount_of_reconciliation_id:
        _supersede_same_day_entries(db, s, codes)
    db.flush()
    ctx = RecomputeContext(db)
    for code in codes:
        recompute(db, code, s.count_date, ctx)
    if s.plan_id:
        for pi in db.scalars(select(CountPlanItem).where(CountPlanItem.plan_id == s.plan_id,
                                                         CountPlanItem.item_code.in_(codes))):
            pi.status = "counted"
    audit.record(db, user, "count.session.finalize", "count_session", s.id,
                 {"snapshot_id": snap.id, "items": len(codes), "stale_override": bool(st["stale"] and allow_stale)})
    return s


def _supersede_same_day_entries(db: Session, s: CountSession, codes: list[str]) -> None:
    others = db.scalars(select(CountEntry).join(CountSession).where(
        CountSession.count_date == s.count_date, CountSession.status == "finalized", CountSession.id != s.id,
        CountEntry.item_code.in_(codes), CountEntry.superseded_by_id.is_(None)))
    now = utcnow()
    for e in others:
        e.superseded_at = now
        e.correction_reason = f"superseded by recount session #{s.id}"


# ------------------------------------------------------------------ reconciliation
def _active_entries(db: Session, item_code: str, count_date: date) -> tuple[list[CountEntry], list[CountSession]]:
    rows = db.execute(select(CountEntry, CountSession).join(CountSession).where(
        CountEntry.item_code == item_code, CountSession.count_date == count_date,
        CountSession.status == "finalized", CountEntry.superseded_by_id.is_(None),
        CountEntry.superseded_at.is_(None))).all()
    return [r[0] for r in rows], list({r[1].id: r[1] for r in rows}.values())


def current_reconciliation(db: Session, item_code: str, count_date: date) -> Reconciliation | None:
    return db.scalars(select(Reconciliation).where(Reconciliation.item_code == item_code,
                                                   Reconciliation.count_date == count_date,
                                                   Reconciliation.superseded.is_(False))).first()


class RecomputeContext:
    """Caches rule sets and the current analysis while many items are recomputed in one go."""

    def __init__(self, db: Session):
        self.db = db
        self._rules: dict[date, object] = {}
        run = analysis.current_run(db)
        self.classes = {c: r.classification for c, r in analysis.primary_results(db, run.id).items()} if run else {}

    def rule_set(self, on: date):
        if on not in self._rules:
            self._rules[on] = rules.active_rule_set(self.db, on)
        return self._rules[on]


def recompute(db: Session, item_code: str, count_date: date, ctx: RecomputeContext | None = None) -> Reconciliation | None:
    entries, sessions = _active_entries(db, item_code, count_date)
    old = current_reconciliation(db, item_code, count_date)
    if not entries:
        if old is not None:
            old.superseded = True
        return None
    ctx = ctx or RecomputeContext(db)
    rs = ctx.rule_set(count_date)
    p = rules.params_of(rs)["reconciliation"]
    phys = recon_engine.aggregate(recon_engine.EntryQty(e.bucket, e.qty) for e in entries)
    latest = max(sessions, key=lambda x: (x.finalized_at.timestamp() if x.finalized_at else 0.0, x.id))
    snap = db.get(InventorySnapshot, latest.snapshot_id) if latest.snapshot_id else None
    odoo = sync.balances(db, snap, [item_code])[item_code]
    res = recon_engine.reconcile(phys, odoo, float(p["abs_tolerance"]), p["uncounted_bucket"], p["missing_odoo"])
    cls_name = ctx.classes.get(item_code)
    vals = dict(phys_wh=res.phys_wh, phys_prod=res.phys_prod, odoo_wh=res.odoo_wh, odoo_prod=res.odoo_prod,
                disc_wh=res.disc_wh, disc_prod=res.disc_prod, has_discrepancy=res.has_discrepancy, status=res.status)
    if old is not None and all(getattr(old, k) == v for k, v in vals.items()) and old.snapshot_id == (snap.id if snap else None):
        return old
    new = Reconciliation(item_code=item_code, count_date=count_date, snapshot_id=snap.id if snap else None,
                         rule_set_id=rs.id, classification_at_count=(old.classification_at_count if old else None)
                         or cls_name,
                         counted_by=", ".join(sorted({x.counted_by_name for x in sessions})),
                         review_status="open" if res.has_discrepancy else "n_a", **vals)
    db.add(new)
    db.flush()
    if old is not None:
        old.superseded, old.superseded_by_id = True, new.id
    return new


def current_reconciliations(db: Session) -> dict[str, Reconciliation]:
    """Latest (by count date) non-superseded reconciliation per item: the Masterlist's K/M..U."""
    out: dict[str, Reconciliation] = {}
    for r in db.scalars(select(Reconciliation).where(Reconciliation.superseded.is_(False))
                        .order_by(Reconciliation.count_date, Reconciliation.id)):
        out[r.item_code] = r
    return out


def review(db: Session, user: User, recon_id: int, action: str, note: str = "", assignee_id: int | None = None) -> DiscrepancyNote:
    """Discrepancy review workflow (Task.md §7 step 10). Never touches Odoo."""
    allowed = {"comment": None, "investigating": "investigating", "recount_requested": "recount_requested",
               "resolved": "resolved", "reopened": "open"}
    if action not in allowed:
        raise CountError("unknown review action")
    r = db.get(Reconciliation, recon_id)
    if r is None:
        raise CountError("reconciliation not found")
    if action in ("resolved",) and not note.strip():
        raise CountError("explain the resolution")
    n = DiscrepancyNote(reconciliation_id=r.id, action=action, note=note.strip(), assigned_to_id=assignee_id,
                        created_by_id=user.id)
    db.add(n)
    if allowed[action]:
        r.review_status = allowed[action]
    if action == "recount_requested":
        plan = db.scalars(select(CountPlan).where(CountPlan.name == "Recount requests", CountPlan.status == "open")).first()
        if plan is None:
            plan = CountPlan(name="Recount requests", plan_date=date.today(), created_by_id=user.id)
            db.add(plan)
            db.flush()
        if not any(pi.item_code == r.item_code for pi in plan.items):
            plan.items.append(CountPlanItem(item_code=r.item_code, reason="recount", priority=0,
                                            assigned_to_id=assignee_id))
    audit.record(db, user, f"discrepancy.{action}", "reconciliation", r.id, {"note": note, "assignee_id": assignee_id})
    return n


def history(db: Session, item_code: str) -> dict:
    entries = db.execute(select(CountEntry, CountSession).join(CountSession).where(CountEntry.item_code == item_code)
                         .order_by(CountSession.count_date.desc(), CountEntry.id)).all()
    recons = db.scalars(select(Reconciliation).where(Reconciliation.item_code == item_code)
                        .order_by(Reconciliation.count_date.desc(), Reconciliation.id.desc())).all()
    notes = defaultdict(list)
    for n in db.scalars(select(DiscrepancyNote).where(DiscrepancyNote.reconciliation_id.in_([r.id for r in recons]))
                        .order_by(DiscrepancyNote.created_at)):
        notes[n.reconciliation_id].append(n)
    return {"entries": entries, "reconciliations": recons, "notes": notes}
