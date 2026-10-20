"""AMC (Average Monthly Consumption) and demand-series rules.

Legacy source: 03_AMC Sep-Jul ABC Analysis.xlsx, family sheets columns D:O, P, R, AB
(see docs/analysis/03-formula-register.md F-01, F-02, F-05, F-13, F-20).

A demand series is a list aligned to the analysis period months. ``None`` means "no demand
record for that month" (Excel ``""``); ``0.0`` is an explicit zero. The two are never mixed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Sequence

Series = Sequence[float | None]

AMC_RECORDED_MONTHS = "recorded_months"  # legacy: AVERAGE() over numeric months only
AMC_PERIOD_MONTHS = "period_months"  # alternative: total / number of months in period


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


@dataclass(frozen=True)
class Period:
    """Consecutive calendar months, identified by their first day."""

    start: date
    months_count: int

    def __post_init__(self) -> None:
        if self.start.day != 1:
            object.__setattr__(self, "start", self.start.replace(day=1))
        if self.months_count < 1:
            raise ValueError("period must contain at least one month")

    @classmethod
    def between(cls, start: date, end: date) -> "Period":
        """Inclusive month range ``start``..``end``."""
        n = (end.year - start.year) * 12 + end.month - start.month + 1
        return cls(start.replace(day=1), n)

    @property
    def months(self) -> list[date]:
        return [add_months(self.start, i) for i in range(self.months_count)]

    @property
    def end(self) -> date:
        return add_months(self.start, self.months_count - 1)

    def label(self) -> str:
        return f"{self.start:%b %Y} – {self.end:%b %Y}"


def monthly_series(demand_by_month: Mapping[date, float | None], period: Period) -> list[float | None]:
    """Align a {month: qty} mapping to the period. Absent months are ``None`` (missing)."""
    out: list[float | None] = []
    for m in period.months:
        v = demand_by_month.get(m)
        out.append(None if v is None else float(v))
    return out


def recorded(series: Iterable[float | None]) -> list[float]:
    return [v for v in series if v is not None]


def total_demand(series: Series) -> float:
    """F-02 ``SUM(D:O)``: missing months contribute nothing."""
    return float(sum(recorded(series)))


def frequency(series: Series) -> int:
    """F-05 ``COUNT(D:O)``: months holding a value, explicit zeros included."""
    return len(recorded(series))


def amc(series: Series, method: str = AMC_RECORDED_MONTHS) -> float:
    """F-13 ``IFERROR(AVERAGE(D:O),0)``.

    ``recorded_months`` (legacy, default): mean of months with a value; 0 when none.
    ``period_months``: total divided by the number of months in the period.
    """
    vals = recorded(series)
    if method == AMC_RECORDED_MONTHS:
        return sum(vals) / len(vals) if vals else 0.0
    if method == AMC_PERIOD_MONTHS:
        return sum(vals) / len(series) if len(series) else 0.0
    raise ValueError(f"unknown AMC method {method!r}")


def stock_in_months(phys_wh: float | None, phys_prod: float | None, amc_value: float | None) -> float | None:
    """F-20 ``(M+N)/E``, corrected per BR-22/BR-29.

    Returns ``None`` when nothing was counted or AMC is missing/non-positive, instead of
    Excel's misleading 0 / "".
    """
    if phys_wh is None and phys_prod is None:
        return None
    if amc_value is None or amc_value <= 0:
        return None
    return ((phys_wh or 0.0) + (phys_prod or 0.0)) / amc_value
