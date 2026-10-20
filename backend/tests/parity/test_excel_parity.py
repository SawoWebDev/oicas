"""Excel-parity tests: the OICAS engine must reproduce the cached results of the legacy workbooks.

Each test names the formula-register entry (docs/analysis/03-formula-register.md) it proves.
Known legacy defects are replayed explicitly (legacy_sheet_order, truncated denominator,
uncounted bucket = 0) so formula equivalence can be shown separately from the corrections.
"""
from __future__ import annotations

import math
from collections import defaultdict

import pytest

from oicas.engine import abc, amc, classification, metrics, reconciliation, scheduling

from .conftest import num

LEGACY_PERIOD_MONTHS = 11  # F-09 ``=R/11``


def series_of(row):
    return [num(v) for v in row[3:15]]  # D..O


def close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


# ---------------------------------------------------------------- ABC / AMC (F-02..F-13)
def test_abc_formulas_reproduce_every_family_sheet(amc_wb):
    """Replaying sheet order + the sheet's own P1 reproduces Q, R, T, U, V, W, X, AB on all rows."""
    families, _ = amc_wb
    params = abc.AbcParams(ordering=abc.ORDER_GIVEN)
    checked = 0
    for fam in families:
        inputs = [abc.AbcInput(str(r[1]), series_of(r)) for r in fam.rows]
        out = abc.analyse_family(inputs, LEGACY_PERIOD_MONTHS, params, denominator_override=fam.denominator)
        assert len(out) == len(fam.rows)
        for res, r in zip(out, fam.rows):
            ctx = f"{fam.name} {r[1]}"
            assert close(res.total, num(r[15]) or 0.0), ctx
            assert close(res.share, num(r[16]) or 0.0), ctx
            assert res.frequency == r[17], ctx
            assert close(res.cum_demand_pct, r[19], 1e-12), ctx
            assert close(res.frequency_pct, r[20]), ctx
            assert (res.qty_class, res.freq_class, res.category) == (r[21], r[22], r[23]), ctx
            assert close(amc.amc(res.series), num(r[27]) or 0.0), ctx
            checked += 1
    assert checked == 6362


def test_abc_ranked_engine_matches_correctly_sorted_sheets(amc_wb):
    """BR-07: on sheets already sorted by total demand, the Pareto engine gives identical classes."""
    families, _ = amc_wb
    for fam in families:
        totals = [num(r[15]) or 0.0 for r in fam.rows]
        if any(totals[i] < totals[i + 1] for i in range(len(totals) - 1)):
            continue  # unsorted legacy sheet (DQ-02) – covered by the defect test below
        inputs = [abc.AbcInput(str(r[1]), series_of(r)) for r in fam.rows]
        out = {x.code: x for x in abc.analyse_family(inputs, LEGACY_PERIOD_MONTHS)}
        tied = {t for t in totals if totals.count(t) > 1}
        for r in fam.rows:
            if out[str(r[1])].category != r[23]:
                # Only ties may differ: Excel keeps equal totals in arbitrary sheet order, OICAS
                # orders ties by item code (BR-07). The item must share its total with another.
                assert (num(r[15]) or 0.0) in tied, f"{fam.name} {r[1]}"


def test_documented_abc_defects_are_real(amc_wb):
    """DQ-01/DQ-02 evidence: RM denominator is truncated and RM/List excluded are unsorted."""
    families = {f.name: f for f in amc_wb[0]}
    rm = families["RM"]
    full_total = sum(num(r[15]) or 0.0 for r in rm.rows)
    assert rm.denominator < full_total  # SUM(P3:P678) vs 907 rows
    assert rm.rows[-1][19] > 1.2  # cumulative % ends above 120 %
    for name in ("RM", "List excluded"):
        t = [num(r[15]) or 0.0 for r in families[name].rows]
        assert any(t[i] < t[i + 1] for i in range(len(t) - 1)), name


def test_classification_matrix_reproduces_y_z_aa_and_interval(amc_wb):
    """F-12/F-14: Y, Z, AA from (category, frequency); CONSOLIDATED AE key and AF days."""
    _, cons = amc_wb
    for r in cons:
        c = classification.classify(r[23], r[17])
        ctx = r[1]
        assert (c.declared_type, c.action, c.classification) == (r[24], r[25], r[26]), ctx
        assert c.interval_key == r[30], ctx
        assert c.interval_days == r[31], ctx


# ---------------------------------------------------------------- Masterlist (F-16..F-23)
def _legacy_list_index(counted_rows):
    by_code = defaultdict(list)
    for r in counted_rows:
        by_code[str(r[1]).strip().casefold()].append(r)  # Excel lookups are case-insensitive
    return by_code


def test_masterlist_latest_count_odoo_and_discrepancy(master_wb, counted_wb):
    """K = MAXIFS date; M/N = SUMIFS on that date; P/Q = first line's Odoo; R/S = M−P, N−Q; U flag;
    L = K + I; O = (M+N)/E. Replayed with the legacy 'uncounted bucket = 0' policy."""
    master, _, _ = master_wb
    idx = _legacy_list_index(counted_wb)
    counted = 0
    for m in master:
        lines = idx.get(str(m[0]).strip().casefold(), [])
        dates = [r[0] for r in lines if r[0]]
        if not dates:
            assert m[10] in (None, ""), m[0]
            assert m[20] == 0, m[0]
            continue
        k = max(dates)
        assert m[10] == k, m[0]
        day = [r for r in lines if r[0] == k]
        phys = reconciliation.aggregate(
            [reconciliation.EntryQty(reconciliation.WAREHOUSE, num(r[3]) or 0.0) for r in day]
            + [reconciliation.EntryQty(reconciliation.PRODUCTION, num(r[4])) for r in day if num(r[4]) is not None])
        odoo = {reconciliation.WAREHOUSE: num(day[0][15]) or 0.0, reconciliation.PRODUCTION: num(day[0][16]) or 0.0}
        res = reconciliation.reconcile(phys, odoo, uncounted_bucket=reconciliation.UNCOUNTED_AS_ZERO)
        assert close(res.phys_wh, m[12]) and close(res.phys_prod, m[13]), m[0]
        assert close(res.disc_wh, m[17]) and close(res.disc_prod, m[18]), m[0]
        assert int(res.has_discrepancy) == m[20], m[0]
        assert scheduling.next_due(k, m[8]) == m[11], m[0]
        if num(m[4]) and m[4] > 0:
            assert close(amc.stock_in_months(res.phys_wh, res.phys_prod, m[4]), m[14]), m[0]
        counted += 1
    assert counted == 1244


def test_counted_list_discrepancy_sign(counted_wb):
    """F-22: LIST R = D − P on every line holding both values."""
    n = 0
    for r in counted_wb:
        if num(r[17]) is not None and num(r[15]) is not None:
            assert close(reconciliation.discrepancy(num(r[3]) or 0.0, r[15]), r[17]), r[1]
            n += 1
    assert n == 2209


# ---------------------------------------------------------------- Progress (F-24, F-25)
def test_progress_overall_matches(master_wb):
    master, po, _ = master_wb
    items = [metrics.ItemProgress(str(m[0]), m[3], m[10] not in (None, ""), m[20] == 1) for m in master]
    k = metrics.overall(items)
    cols = {"FAST MOVING": classification.FAST, "MEDIUM MOVING": classification.MEDIUM,
            "SLOW MOVING": classification.SLOW, "NON MOVING": classification.NON}
    for ci, header in enumerate(po[0][1:5], start=1):
        kp = k[cols[header]]
        assert kp.items == po[1][ci]
        assert kp.counted == po[2][ci]
        assert kp.discrepancies == po[3][ci]
        assert close(kp.completion, po[4][ci])
        assert close(kp.accuracy, po[5][ci])
        assert close(kp.overall_accuracy, po[6][ci])
        assert close(kp.discrepancy_rate, po[7][ci])


def test_weekly_labels_match_excel_weeknum(master_wb):
    _, _, pw = master_wb
    for r in pw[1:5]:
        d = r[0].date()
        assert f"WK#{metrics.excel_weeknum_monday(d)}" == r[1]
        assert metrics.week_end(d) == d  # legacy DATE column holds the Sunday week-end


@pytest.mark.parametrize("d,expected", [("2026-01-01", 1), ("2026-01-04", 1), ("2026-01-05", 2),
                                         ("2026-08-31", 36), ("2026-09-06", 36), ("2026-09-07", 37)])
def test_weeknum_edge_cases(d, expected):
    from datetime import date
    assert metrics.excel_weeknum_monday(date.fromisoformat(d)) == expected
