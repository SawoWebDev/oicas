"""End-to-end parity: migrate the three legacy workbooks into OICAS and compare the resulting
Masterlist with W2 ``Master`` item by item.

Run once under the *legacy replay* rule set (uncounted bucket = 0, as Excel's SUMIFS does) to
prove the pipeline reproduces Excel, and once under the default rule set to measure the effect
of BR-22 (an uncounted PROD location is not a confirmed zero).
"""
from __future__ import annotations

from datetime import date

import pytest

from oicas.db import Base, make_engine, session_factory, set_engine
from oicas.services import importers, inventory, rules

from .conftest import REF


def _migrate(policy: str):
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    set_engine(eng)
    db = session_factory()()
    rs = rules.ensure_default_rule_set(db)
    legacy = policy == "zero"
    rs.params = rules.merged_params({**rs.params, "reconciliation": {
        "abs_tolerance": 0.0, "uncounted_bucket": policy, "missing_odoo": "zero" if legacy else "missing"}})
    db.flush()
    importers.import_reference_set(db, None, REF)
    db.commit()
    return db


@pytest.fixture(scope="module")
def legacy_db():
    if not (REF / "COUNTED LIST.xlsx").exists():
        pytest.skip("reference workbooks not available")
    return _migrate("zero")


def stale_copies(master, cons) -> set[str]:
    """DQ-06: Masterlist rows whose (action, classification) matches no CONSOLIDATED row of the code
    (the manual copy from the AMC workbook is out of date)."""
    by_code: dict[str, set] = {}
    for r in cons:
        by_code.setdefault(str(r[1]).strip(), set()).add((r[25], r[26]))
    return {str(m[0]).strip() for m in master if (m[2], m[3]) not in by_code.get(str(m[0]).strip(), set())}


def test_migrated_masterlist_matches_excel_item_by_item(legacy_db, master_wb, amc_wb):
    master, _, _ = master_wb
    drift = stale_copies(master, amc_wb[1])
    assert 0 < len(drift) < 60  # documented size of DQ-06
    rows = {r.code: r for r in inventory.build(legacy_db, as_of=date(2026, 10, 13)).rows}
    first = {}
    dup = set()
    for m in master:
        code = str(m[0]).strip()
        if code in first:
            dup.add(code)
        first.setdefault(code, m)
    mismatches = []
    for code, m in first.items():
        r = rows[code]
        exp_counted = m[10] not in (None, "")
        got = (r.classification, r.action, r.interval_days, r.counted, r.last_count_date if r.counted else None,
               int(r.has_discrepancy) if r.counted else 0)
        exp = (m[3], m[2], m[8], exp_counted, m[10] if exp_counted else None, m[20])
        if got != exp:
            mismatches.append((code, got, exp))
    # Allowed, documented differences only:
    #  - codes duplicated in the Masterlist (DQ-04): Excel keeps one row per family copy;
    #  - codes whose latest LIST line has no quantity (DQ-23): Excel treats it as a count of 0.
    from sqlalchemy import select

    from oicas.models import DqException
    blank = {e.ref.split("/", 1)[1] for e in legacy_db.scalars(
        select(DqException).where(DqException.kind == "count_line_without_qty"))}
    unexplained = [m for m in mismatches if m[0] not in dup | blank | drift]
    assert not unexplained, unexplained[:5]
    assert len(rows) == len(first) == 6086
    print(f"\nmigration parity: {len(first)} items, {len(mismatches)} explained differences "
          f"(dup rows {len(dup)}, blank lines {len(blank)}, stale copies {len(drift)})")


def test_migrated_progress_matches_excel_after_dedup(legacy_db, master_wb, amc_wb):
    """PROGRESS-overall per class equals Excel computed over unique codes, excluding the items whose
    latest Excel 'count' was a blank line (DQ-23) and stale Masterlist copies (DQ-06)."""
    from sqlalchemy import select

    from oicas.models import DqException
    blank = {e.ref.split("/", 1)[1] for e in legacy_db.scalars(
        select(DqException).where(DqException.kind == "count_line_without_qty"))}
    master, po, _ = master_wb
    blank |= stale_copies(master, amc_wb[1])
    rows = [r for r in inventory.build(legacy_db, as_of=date(2026, 10, 13)).rows if r.code not in blank]
    k = inventory.overall_kpis(rows)
    seen, exp = set(blank), {}
    for m in master:
        code = str(m[0]).strip()
        if code in seen:
            continue
        seen.add(code)
        e = exp.setdefault(m[3], [0, 0, 0])
        e[0] += 1
        e[1] += m[10] not in (None, "")
        e[2] += m[20] == 1
    for cls, (items, counted, disc) in exp.items():
        assert (k[cls].items, k[cls].counted, k[cls].discrepancies) == (items, counted, disc), cls


def test_default_policy_effect_is_measured(legacy_db):
    """BR-22 impact report: how many legacy 'discrepancies' were only an uncounted PROD balance."""
    legacy = inventory.overall_kpis(inventory.build(legacy_db, as_of=date(2026, 10, 13)).rows)
    current = inventory.overall_kpis(inventory.build(_migrate("not_counted"), as_of=date(2026, 10, 13)).rows)
    for c in legacy:
        assert current[c].counted == legacy[c].counted
        assert current[c].discrepancies <= legacy[c].discrepancies
    print({c: (legacy[c].discrepancies, current[c].discrepancies) for c in legacy})
