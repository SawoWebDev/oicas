"""ABC analysis (demand quantity and demand frequency), per material-section family.

Legacy source: 03_AMC Sep-Jul ABC Analysis.xlsx family sheets P..X
(docs/analysis/03-formula-register.md F-02..F-11, business rules BR-06..BR-10).

Accumulation reproduces Excel exactly: ``T(n) = T(n-1) + P(n)/P1`` in IEEE double, and the
thresholds compare the cumulative *including* the current item.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from . import amc as amc_mod

ORDER_DEMAND_DESC = "demand_desc"  # approved/default: Pareto ranking (UD-01)
ORDER_GIVEN = "legacy_sheet_order"  # parity replay: keep the input order exactly


@dataclass(frozen=True)
class AbcParams:
    qty_a_below: float = 0.80  # V: A if cumulative < 80 %
    qty_c_from: float = 0.95  # V: C if cumulative >= 95 %
    freq_a_above: float = 0.80  # W: A if frequency % > 80 %
    freq_c_upto: float = 0.50  # W: C if frequency % <= 50 %
    ordering: str = ORDER_DEMAND_DESC

    def validate(self) -> None:
        if not 0 < self.qty_a_below <= self.qty_c_from <= 1:
            raise ValueError("require 0 < qty_a_below <= qty_c_from <= 1")
        if not 0 <= self.freq_c_upto <= self.freq_a_above <= 1:
            raise ValueError("require 0 <= freq_c_upto <= freq_a_above <= 1")
        if self.ordering not in (ORDER_DEMAND_DESC, ORDER_GIVEN):
            raise ValueError(f"unknown ordering {self.ordering!r}")

    @classmethod
    def from_dict(cls, d: dict) -> "AbcParams":
        keys = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass(frozen=True)
class AbcInput:
    code: str
    series: Sequence[float | None]


@dataclass
class AbcRow:
    code: str
    series: list[float | None]
    total: float
    share: float
    frequency: int
    frequency_pct: float
    rank: int
    cum_items_pct: float
    cum_demand_pct: float
    qty_class: str
    freq_class: str
    category: str = field(init=False)

    def __post_init__(self) -> None:
        self.category = self.qty_class + self.freq_class


def qty_class(cum: float, p: AbcParams) -> str:
    """F-08 ``IF(T<80%,"A",IF(T>=95%,"C","B"))``."""
    if cum < p.qty_a_below:
        return "A"
    if cum >= p.qty_c_from:
        return "C"
    return "B"


def freq_class(freq_pct: float, p: AbcParams) -> str:
    """F-10 ``IF(U>80%,"A",IF(U<=50%,"C","B"))``."""
    if freq_pct > p.freq_a_above:
        return "A"
    if freq_pct <= p.freq_c_upto:
        return "C"
    return "B"


def analyse_family(
    items: Sequence[AbcInput],
    period_months: int,
    params: AbcParams | None = None,
    denominator_override: float | None = None,
) -> list[AbcRow]:
    """Run ABC for one family.

    ``period_months`` is the frequency-% divisor (legacy hard-coded 11, F-09).
    ``denominator_override`` exists only to replay legacy defects (DQ-01) in parity tests.
    Returns rows in ranked order.
    """
    p = params or AbcParams()
    p.validate()
    if period_months < 1:
        raise ValueError("period_months must be >= 1")
    prepared = [(it.code, list(it.series), amc_mod.total_demand(it.series)) for it in items]
    if p.ordering == ORDER_DEMAND_DESC:
        prepared.sort(key=lambda t: (-t[2], t[0]))
    family_total = denominator_override if denominator_override is not None else sum(t[2] for t in prepared)
    n = len(prepared)
    out: list[AbcRow] = []
    cum = 0.0
    for idx, (code, series, total) in enumerate(prepared, start=1):
        share = total / family_total if family_total else 0.0
        cum = share if idx == 1 else cum + share
        freq = amc_mod.frequency(series)
        fpct = freq / period_months
        out.append(
            AbcRow(
                code=code,
                series=series,
                total=total,
                share=share,
                frequency=freq,
                frequency_pct=fpct,
                rank=idx,
                cum_items_pct=idx / n,
                cum_demand_pct=cum,
                qty_class=qty_class(cum, p),
                freq_class=freq_class(fpct, p),
            )
        )
    return out
