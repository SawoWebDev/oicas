"""Progress and accuracy metrics.

Legacy source: PROGRESS-overall and PROGRESS-weekly
(docs/analysis/03-formula-register.md F-24, F-25; BR-20, BR-21).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from .classification import MOVEMENT_CLASSES


def ratio(num: float, den: float) -> float | None:
    """Excel would show #DIV/0!; OICAS returns ``None`` (rendered as "–")."""
    return num / den if den else None


@dataclass(frozen=True)
class ItemProgress:
    code: str
    classification: str | None
    counted: bool  # has at least one finalized count (Master K <> "")
    has_discrepancy: bool  # latest count has a discrepancy (Master U = 1)


@dataclass
class OverallKpi:
    classification: str
    items: int
    counted: int
    discrepancies: int

    @property
    def remaining(self) -> int:
        return self.items - self.counted

    @property
    def accurate(self) -> int:
        return self.counted - self.discrepancies

    @property
    def completion(self) -> float | None:  # # counted / # of items
        return ratio(self.counted, self.items)

    @property
    def accuracy(self) -> float | None:  # (# counted − # disc) / # counted
        return ratio(self.counted - self.discrepancies, self.counted)

    @property
    def overall_accuracy(self) -> float | None:  # (# counted − # disc) / # of items
        return ratio(self.counted - self.discrepancies, self.items)

    @property
    def discrepancy_rate(self) -> float | None:  # # disc / # counted
        return ratio(self.discrepancies, self.counted)

    def as_dict(self) -> dict:
        return {
            "classification": self.classification, "items": self.items, "counted": self.counted,
            "remaining": self.remaining, "discrepancies": self.discrepancies, "accurate": self.accurate,
            "completion": self.completion, "accuracy": self.accuracy,
            "overall_accuracy": self.overall_accuracy, "discrepancy_rate": self.discrepancy_rate,
        }


def overall(items: Iterable[ItemProgress], classes: Iterable[str] = MOVEMENT_CLASSES) -> dict[str, OverallKpi]:
    out = {c: OverallKpi(c, 0, 0, 0) for c in classes}
    for it in items:
        k = out.get(it.classification or "")
        if k is None:
            continue
        k.items += 1
        if it.counted:
            k.counted += 1
            if it.has_discrepancy:
                k.discrepancies += 1
    return out


def total_of(kpis: dict[str, OverallKpi]) -> OverallKpi:
    t = OverallKpi("Total", 0, 0, 0)
    for k in kpis.values():
        t.items += k.items
        t.counted += k.counted
        t.discrepancies += k.discrepancies
    return t


def excel_weeknum_monday(d: date) -> int:
    """Excel ``WEEKNUM(d, 2)``: week 1 contains 1 Jan, weeks start on Monday."""
    jan1 = date(d.year, 1, 1)
    return (d.timetuple().tm_yday - 1 + jan1.weekday()) // 7 + 1


def week_end(d: date) -> date:
    """Sunday closing the Monday-based week containing ``d`` (legacy DATE column)."""
    return d + timedelta(days=6 - d.weekday())


@dataclass(frozen=True)
class CountEvent:
    """One reconciled count of an item on a date (one LIST line after aggregation)."""

    code: str
    count_date: date
    classification: str | None
    has_discrepancy: bool


@dataclass
class WeeklyRow:
    classification: str
    week_ending: date
    week_label: str
    total_counted: int
    discrepancy: int
    cumulative_counted: int
    class_items: int

    @property
    def accurate(self) -> int:
        return self.total_counted - self.discrepancy

    @property
    def accuracy(self) -> float | None:
        return ratio(self.accurate, self.total_counted)

    @property
    def completion(self) -> float | None:
        """``SUM($C$2:Cn) / 'PROGRESS-overall'!#items``."""
        return ratio(self.cumulative_counted, self.class_items)

    def as_dict(self) -> dict:
        return {
            "classification": self.classification, "week_ending": self.week_ending,
            "week_label": self.week_label, "total_counted": self.total_counted,
            "discrepancy": self.discrepancy, "accurate": self.accurate, "accuracy": self.accuracy,
            "cumulative_counted": self.cumulative_counted, "completion": self.completion,
        }


def weekly(
    events: Iterable[CountEvent],
    items_per_class: dict[str, int],
    start: date,
    end: date,
    classes: Iterable[str] = MOVEMENT_CLASSES,
) -> dict[str, list[WeeklyRow]]:
    """Weekly blocks per class from ``start`` to ``end`` (inclusive, snapped to Mon–Sun weeks).

    Counted = distinct (item, count date) events in the week; cumulative completion sums the
    weekly counts exactly like the legacy sheet (UD-05).
    """
    buckets: dict[tuple[str, date], set[tuple[str, date]]] = defaultdict(set)
    disc: dict[tuple[str, date], set[tuple[str, date]]] = defaultdict(set)
    for e in events:
        if e.classification is None or not (start <= e.count_date <= end):
            continue
        key = (e.classification, week_end(e.count_date))
        buckets[key].add((e.code, e.count_date))
        if e.has_discrepancy:
            disc[key].add((e.code, e.count_date))
    out: dict[str, list[WeeklyRow]] = {}
    first, last = week_end(start), week_end(end)
    for c in classes:
        rows, cum, we = [], 0, first
        while we <= last:
            n = len(buckets.get((c, we), ()))
            cum += n
            rows.append(WeeklyRow(c, we, f"WK#{excel_weeknum_monday(we)}", n, len(disc.get((c, we), ())), cum,
                                  items_per_class.get(c, 0)))
            we += timedelta(days=7)
        out[c] = rows
    return out
