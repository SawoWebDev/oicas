"""Service-level tests: Odoo sync, counting workflow, reconciliation, analysis, auth, safety rules."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from oicas.db import Base, make_engine, set_engine, session_factory
from oicas.engine.amc import Period
from oicas.models import (AuditLog, CountEntry, DqException, InventorySnapshot, Item, Reconciliation, SnapshotLine,
                          SyncRun)
from oicas.odoo.client import OdooError, ReadOnlyViolation, assert_read_only
from oicas.services import analysis, auth, counting, inventory, reports, rules, sync

from .helpers import fake_odoo, make_user, map_locations, track_items


@pytest.fixture
def db():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    set_engine(eng)
    s = session_factory()()
    rules.ensure_default_rule_set(s)
    yield s
    s.close()


@pytest.fixture
def synced(db):
    gw = fake_odoo()
    run = sync.run_inventory_sync(db, gw)  # first sync discovers locations (unmapped)
    assert run.status == "success"
    map_locations(db)
    run = sync.run_inventory_sync(db, gw)
    track_items(db)
    return db


def kinds(db):
    return {(e.kind, e.ref) for e in db.scalars(select(DqException).where(DqException.status == "open"))}


# ------------------------------------------------------------------ Odoo integration
def test_read_only_whitelist_blocks_writes():
    for m in ("create", "write", "unlink", "action_apply_inventory", "button_validate"):
        with pytest.raises(ReadOnlyViolation):
            assert_read_only(m)
    assert_read_only("search_read")
    with pytest.raises(ReadOnlyViolation):
        fake_odoo().call("stock.quant", "write", [1], {"quantity": 0})


def test_sync_creates_items_snapshot_and_dq(synced):
    db = synced
    items = {i.code: i for i in db.scalars(select(Item))}
    assert set(items) == {"A-1", "A-2", "A-3"}
    assert items["A-3"].odoo_product_id == 3  # duplicate code → lowest product id
    snap = sync.latest_snapshot(db)
    lines = {(l.item_code, l.bucket): l.qty for l in db.scalars(select(SnapshotLine).where(SnapshotLine.snapshot_id == snap.id))}
    assert lines == {("A-1", "WAREHOUSE"): 100.0, ("A-1", "PRODUCTION"): 5.0, ("A-2", "WAREHOUSE"): -2.0}  # QC excluded
    k = kinds(db)
    assert ("duplicate_product_code", "A-3") in k
    assert ("product_without_code", "5") in k
    assert ("unmapped_location", "30") in k
    assert ("negative_odoo_qty", "A-2/WAREHOUSE") in k
    # complete snapshot: known product without stock = 0, unknown product = None
    bal = sync.balances(db, snap, ["A-3", "ZZZ"])
    assert bal["A-3"] == {"WAREHOUSE": 0.0, "PRODUCTION": 0.0}
    assert bal["ZZZ"] == {"WAREHOUSE": None, "PRODUCTION": None}


def test_failed_sync_is_logged_and_creates_no_snapshot(db):
    before = db.scalar(select(InventorySnapshot.id).limit(1))
    run = sync.run_inventory_sync(db, fake_odoo(fail="stock.quant"))
    assert run.status == "failed" and "simulated outage" in run.error
    assert db.scalar(select(InventorySnapshot.id).limit(1)) == before
    assert db.scalars(select(Item)).first() is None  # product upserts rolled back with the savepoint
    assert ("sync_failed", f"inventory#{run.id}") in kinds(db)
    st = sync.staleness(db, sync.latest_snapshot(db))
    assert st["stale"] and st["snapshot"] is None


def test_demand_sync_buckets_by_local_month_and_skips_cancelled(synced):
    run = sync.run_demand_sync(synced, fake_odoo(), Period(date(2025, 9, 1), 2))
    assert run.status == "success", run.error
    from oicas.models import DemandLine
    lines = {(l.item_code, l.month): l.qty for l in synced.scalars(select(DemandLine))}
    assert lines == {("A-1", date(2025, 9, 1)): 10.0, ("A-1", date(2025, 10, 1)): 5.0}


# ------------------------------------------------------------------ counting workflow
def _count(db, user, code="A-1", wh=(98.0,), prod=(), d=None, finalize=True, **kw):
    s = counting.create_session(db, user, d or date.today(), "Christine A", **kw)
    for i, q in enumerate(wh, start=1):
        counting.add_entry(db, user, s.id, code, "WAREHOUSE", q, str(i))
    for i, q in enumerate(prod, start=1):
        counting.add_entry(db, user, s.id, code, "PRODUCTION", q, str(i))
    counting.submit(db, user, s.id)
    if finalize:
        counting.finalize(db, user, s.id)
    return s


def test_count_finalize_reconcile_signed_variance(synced):
    db, u = synced, make_user(synced)
    _count(db, u, wh=(60.0, 38.0))  # WH-1 + WH-2 = 98 (LIST D = SUM(H:K))
    rc = counting.current_reconciliation(db, "A-1", date.today())
    assert rc.phys_wh == 98.0 and rc.odoo_wh == 100.0 and rc.disc_wh == -2.0
    assert rc.phys_prod is None and rc.disc_prod is None  # PROD not counted ≠ 0 (BR-22)
    assert rc.has_discrepancy and rc.status == "discrepancy" and rc.review_status == "open"


def test_uncounted_bucket_legacy_policy_counts_as_zero(synced):
    db, u = synced, make_user(synced)
    rs = rules.create_rule_set(db, u, "legacy replay", date.today(),
                               {"reconciliation": {"uncounted_bucket": "zero"}}, rules.active_rule_set(db).class_matrix, None)
    assert rs.version == 2
    _count(db, u, wh=(100.0,))
    rc = counting.current_reconciliation(db, "A-1", date.today())
    assert rc.disc_wh == 0.0 and rc.disc_prod == -5.0 and rc.has_discrepancy


def test_accurate_and_counted_zero(synced):
    db, u = synced, make_user(synced)
    _count(db, u, code="A-3", wh=(0.0,))  # explicit zero vs complete snapshot (no stock) → accurate
    rc = counting.current_reconciliation(db, "A-3", date.today())
    assert rc.phys_wh == 0.0 and rc.odoo_wh == 0.0 and rc.status == "accurate" and not rc.has_discrepancy


def test_entries_immutable_after_submit_and_corrections_supersede(synced):
    db, u = synced, make_user(synced)
    s = _count(db, u, wh=(98.0,))
    e = s.entries[0]
    with pytest.raises(counting.CountError):
        counting.add_entry(db, u, s.id, "A-1", "WAREHOUSE", 1.0)
    with pytest.raises(counting.CountError):
        counting.remove_draft_entry(db, u, e.id)
    with pytest.raises(counting.CountError):
        counting.correct_entry(db, u, e.id, 100.0, "")
    new = counting.correct_entry(db, u, e.id, 100.0, "miscounted pallet")
    assert db.get(CountEntry, e.id).superseded_by_id == new.id and db.get(CountEntry, e.id).qty == 98.0
    current = counting.current_reconciliation(db, "A-1", date.today())
    assert current.disc_wh == 0.0 and not current.has_discrepancy
    hist = db.scalars(select(Reconciliation).where(Reconciliation.item_code == "A-1")).all()
    assert len(hist) == 2 and sum(r.superseded for r in hist) == 1  # history kept
    assert db.scalars(select(AuditLog).where(AuditLog.action == "count.entry.correct")).first() is not None


def test_idempotent_session_creation(synced):
    db, u = synced, make_user(synced)
    a = counting.create_session(db, u, date.today(), "X", client_token="tok-1")
    b = counting.create_session(db, u, date.today(), "X", client_token="tok-1")
    assert a.id == b.id


def test_validation_rules(synced):
    db, u = synced, make_user(synced)
    s = counting.create_session(db, u, date.today(), "X")
    for args in (("NOPE", "WAREHOUSE", 1.0), ("A-1", "SHELF", 1.0), ("A-1", "WAREHOUSE", -1.0)):
        with pytest.raises(counting.CountError):
            counting.add_entry(db, u, s.id, *args)
    with pytest.raises(counting.CountError):
        counting.add_entry(db, u, s.id, "A-1", "WAREHOUSE", 1.0, slot="9")
    with pytest.raises(counting.CountError):
        counting.submit(db, u, s.id)  # empty session
    with pytest.raises(counting.CountError):
        counting.create_session(db, u, date.today() + timedelta(days=1), "X")


def test_stale_snapshot_blocks_finalize_unless_confirmed(synced):
    db, u = synced, make_user(synced)
    for snap in db.scalars(select(InventorySnapshot)):
        snap.taken_at = snap.taken_at - timedelta(hours=48)
    s = _count(db, u, finalize=False)
    with pytest.raises(counting.StaleSnapshotError):
        counting.finalize(db, u, s.id)
    counting.finalize(db, u, s.id, allow_stale=True)
    assert s.status == "finalized"


def test_same_day_entries_are_summed_and_recount_supersedes(synced):
    db, u = synced, make_user(synced)
    _count(db, u, wh=(50.0,))
    _count(db, u, wh=(40.0,))  # second line same day (legacy SUMIFS adds them)
    rc = counting.current_reconciliation(db, "A-1", date.today())
    assert rc.phys_wh == 90.0
    counting.review(db, u, rc.id, "recount_requested", "check bin 3")
    assert rc.review_status == "recount_requested"
    _count(db, u, wh=(100.0,), recount_of=rc.id)
    rc2 = counting.current_reconciliation(db, "A-1", date.today())
    assert rc2.phys_wh == 100.0 and rc2.status == "accurate"


def test_review_requires_resolution_note(synced):
    db, u = synced, make_user(synced)
    _count(db, u)
    rc = counting.current_reconciliation(db, "A-1", date.today())
    with pytest.raises(counting.CountError):
        counting.review(db, u, rc.id, "resolved", "")
    counting.review(db, u, rc.id, "resolved", "Odoo adjusted by stock controller")
    assert rc.review_status == "resolved"


# ------------------------------------------------------------------ analysis, masterlist, metrics
def test_analysis_run_approve_and_masterlist(synced):
    db, u = synced, make_user(synced)
    from oicas.models import DemandBatch, DemandLine
    b = DemandBatch(source="excel", label="t", period_start=date(2025, 9, 1), period_end=date(2025, 11, 1))
    db.add(b)
    db.flush()
    for m in (9, 10, 11):
        db.add(DemandLine(batch_id=b.id, item_code="A-1", month=date(2025, m, 1), qty=100.0))
    db.add(DemandLine(batch_id=b.id, item_code="A-2", month=date(2025, 9, 1), qty=1.0))
    run = analysis.run_analysis(db, u, b.id, Period(date(2025, 9, 1), 3))
    res = analysis.primary_results(db, run.id)
    # A-1 is 99.7 % of family demand: cumulative incl. itself ≥ 95 % → qty class C (legacy F-08), freq 3/3 → A
    assert res["A-1"].category == "CA" and res["A-1"].classification == "Medium Moving" and res["A-1"].amc == 100.0
    assert res["A-3"].frequency == 0 and res["A-3"].classification == "Non Moving"
    assert analysis.current_run(db) is None  # drafts never drive the masterlist
    analysis.approve(db, u, run.id)
    _count(db, u, wh=(98.0,))
    ds = inventory.build(db)
    row = next(r for r in ds.rows if r.code == "A-1")
    assert row.interval_days == 90 and row.next_due == date.today() + timedelta(days=90)
    assert row.stock_in_months == pytest.approx(98.0 / 100.0)
    never = next(r for r in ds.rows if r.code == "A-2")
    assert never.last_count_date is None and never.phys_wh is None and never.stock_in_months is None
    assert never.due_status == "due_today"  # UD-04 default: due on approval date
    k = inventory.overall_kpis(ds.rows)
    assert k["Medium Moving"].items == 1 and k["Medium Moving"].counted == 1 and k["Medium Moving"].discrepancies == 1


def test_every_report_builds_and_exports(synced):
    from oicas.services import exports
    db, u = synced, make_user(synced)
    _count(db, u)
    for key in reports.REGISTRY:
        res = reports.run(db, key, {})
        assert res.columns, key
        x, _, _ = exports.export(db, u, res, "xlsx", {})
        p, _, _ = exports.export(db, u, res, "pdf", {})
        assert x[:2] == b"PK" and p[:4] == b"%PDF", key


def test_xlsx_export_matches_screen_values(synced):
    import io

    from openpyxl import load_workbook

    from oicas.services import exports
    db, u = synced, make_user(synced)
    _count(db, u, wh=(98.0,))
    res = reports.run(db, "reconciliation", {})
    wb = load_workbook(io.BytesIO(exports.to_xlsx(res)))
    ws = wb.worksheets[0]
    hdr = next(r for r in range(1, 30) if ws.cell(r, 1).value == "Count date")
    labels = [c.label for c in res.columns]
    assert [ws.cell(hdr, i + 1).value for i in range(len(labels))] == labels
    for i, row in enumerate(res.rows):
        for j, col in enumerate(res.columns):
            v = ws.cell(hdr + 1 + i, j + 1).value
            exp = row.get(col.key)
            if col.kind == "date":
                v = v.date() if v else v
            assert v == exp, (col.key, v, exp)


# ------------------------------------------------------------------ authentication
def test_login_with_odoo_maps_groups_and_throttles(db):
    gw = fake_odoo()
    user, token = auth.login_with_odoo(db, gw, "manager", "demo", "1.1.1.1", "pytest")
    assert user.role == "manager" and token
    user, _ = auth.login_with_odoo(db, gw, "viewer", "demo", "1.1.1.1", "pytest")
    assert user.role == "viewer"
    for _ in range(5):
        with pytest.raises(auth.AuthError):
            auth.login_with_odoo(db, gw, "counter", "wrong", "2.2.2.2", "pytest")
    with pytest.raises(auth.AuthError, match="Too many"):
        auth.login_with_odoo(db, gw, "counter", "demo", "2.2.2.2", "pytest")


def test_odoo_down_login_gives_clear_message(db):
    with pytest.raises(auth.AuthError, match="unreachable"):
        auth.login_with_odoo(db, fake_odoo(fail="all"), "manager", "demo", None, None)


def test_password_hash_roundtrip():
    from oicas import security
    h = security.hash_password("s3cret!")
    assert "s3cret" not in h and security.verify_password("s3cret!", h) and not security.verify_password("x", h)


def test_live_gateway_requires_configuration():
    from oicas.odoo.client import LiveOdoo
    with pytest.raises(OdooError):
        LiveOdoo("", "", "", "")


def test_sync_history_report_lists_runs(synced):
    res = reports.run(synced, "sync_history", {})
    assert len(res.rows) == len(synced.scalars(select(SyncRun)).all())
