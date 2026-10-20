"""Count aggregation and physical-vs-Odoo reconciliation.

Legacy source: COUNTED LIST LIST!D (=SUM(H:K)), R, S; Masterlist M, N, P, Q, R, S, U
(docs/analysis/03-formula-register.md F-18, F-19, F-21..F-23; BR-14..BR-17, BR-22, BR-23).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

WAREHOUSE = "WAREHOUSE"
PRODUCTION = "PRODUCTION"  # "PROD" / "Pre-prod" in the workbooks
BUCKETS = (WAREHOUSE, PRODUCTION)

# How a bucket without count entries is treated when the item *was* counted that day.
UNCOUNTED_AS_MISSING = "not_counted"  # default (Task.md §11): no physical qty, no discrepancy
UNCOUNTED_AS_ZERO = "zero"  # legacy replay: SUMIFS returns 0 → discrepancy = -Odoo

# How a missing Odoo balance is treated.
ODOO_MISSING_AS_MISSING = "missing"  # default (BR-23): status odoo_missing, no variance
ODOO_MISSING_AS_ZERO = "zero"  # legacy replay: XLOOKUP(...,0) → variance against 0 (DQ-08)

FLOAT_NOISE = 1e-6

STATUS_ACCURATE = "accurate"
STATUS_DISCREPANCY = "discrepancy"
STATUS_ODOO_MISSING = "odoo_missing"
STATUS_NOT_COUNTED = "not_counted"


@dataclass(frozen=True)
class EntryQty:
    bucket: str
    qty: float


def aggregate(entries: Iterable[EntryQty], counted_zero_buckets: Iterable[str] = ()) -> dict[str, float | None]:
    """Sum entries per bucket (F-19). A bucket with no entries is ``None`` unless the counter
    explicitly confirmed it as counted-zero."""
    totals: dict[str, float | None] = {b: None for b in BUCKETS}
    for e in entries:
        if e.bucket not in totals:
            raise ValueError(f"unknown bucket {e.bucket!r}")
        totals[e.bucket] = (totals[e.bucket] or 0.0) + float(e.qty)
    for b in counted_zero_buckets:
        if totals.get(b) is None:
            totals[b] = 0.0
    return totals


def discrepancy(physical: float | None, odoo: float | None) -> float | None:
    """F-22 signed ``physical − Odoo``. ``None`` if either side is unknown."""
    if physical is None or odoo is None:
        return None
    return physical - odoo


def is_variance(value: float | None, abs_tolerance: float = 0.0) -> bool:
    """Non-zero variance beyond tolerance (legacy tolerance 0; float noise ignored)."""
    if value is None:
        return False
    return abs(value) > max(abs_tolerance, FLOAT_NOISE)


@dataclass(frozen=True)
class ReconResult:
    phys_wh: float | None
    phys_prod: float | None
    odoo_wh: float | None
    odoo_prod: float | None
    disc_wh: float | None
    disc_prod: float | None
    has_discrepancy: bool
    status: str

    @property
    def abs_variance(self) -> float:
        return abs(self.disc_wh or 0.0) + abs(self.disc_prod or 0.0)

    @property
    def net_variance(self) -> float:
        return (self.disc_wh or 0.0) + (self.disc_prod or 0.0)


def reconcile(
    phys: dict[str, float | None],
    odoo: dict[str, float | None],
    abs_tolerance: float = 0.0,
    uncounted_bucket: str = UNCOUNTED_AS_MISSING,
    missing_odoo: str = ODOO_MISSING_AS_MISSING,
) -> ReconResult:
    """Reconcile one item on one count date against its Odoo snapshot balances.

    ``odoo`` values are ``None`` when the snapshot has no line for the item/bucket (BR-23);
    a product present in the snapshot with no stock in a bucket is 0.0.
    """
    p_wh, p_prod = phys.get(WAREHOUSE), phys.get(PRODUCTION)
    if p_wh is None and p_prod is None:
        return ReconResult(None, None, odoo.get(WAREHOUSE), odoo.get(PRODUCTION), None, None, False, STATUS_NOT_COUNTED)
    if uncounted_bucket == UNCOUNTED_AS_ZERO:
        p_wh, p_prod = p_wh or 0.0, p_prod or 0.0
    elif uncounted_bucket != UNCOUNTED_AS_MISSING:
        raise ValueError(f"unknown uncounted_bucket policy {uncounted_bucket!r}")
    o_wh, o_prod = odoo.get(WAREHOUSE), odoo.get(PRODUCTION)
    if missing_odoo == ODOO_MISSING_AS_ZERO:
        o_wh, o_prod = o_wh or 0.0, o_prod or 0.0
    elif missing_odoo != ODOO_MISSING_AS_MISSING:
        raise ValueError(f"unknown missing_odoo policy {missing_odoo!r}")
    d_wh, d_prod = discrepancy(p_wh, o_wh), discrepancy(p_prod, o_prod)
    flag = is_variance(d_wh, abs_tolerance) or is_variance(d_prod, abs_tolerance)
    missing = (p_wh is not None and o_wh is None) or (p_prod is not None and o_prod is None)
    if flag:
        status = STATUS_DISCREPANCY
    elif missing:
        status = STATUS_ODOO_MISSING
    else:
        status = STATUS_ACCURATE
    return ReconResult(p_wh, p_prod, o_wh, o_prod, d_wh, d_prod, flag, status)
