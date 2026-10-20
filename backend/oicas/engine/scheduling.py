"""Cycle-count scheduling.

Legacy source: Masterlist L ``=K+I`` (docs/analysis/03-formula-register.md F-17; BR-19, BR-26).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .classification import action_priority

NEVER_COUNTED_DUE_NOW = "due_now"  # default (UD-04): due on the anchor date
NEVER_COUNTED_UNSCHEDULED = "unscheduled"  # legacy: blank NEXT COUNT

OVERDUE, DUE_TODAY, UPCOMING, SCHEDULED, UNSCHEDULED = "overdue", "due_today", "upcoming", "scheduled", "unscheduled"


def next_due(
    last_count: date | None,
    interval_days: int | None,
    never_counted: str = NEVER_COUNTED_DUE_NOW,
    anchor: date | None = None,
) -> date | None:
    if interval_days is None or interval_days <= 0:
        return None
    if last_count is not None:
        return last_count + timedelta(days=interval_days)
    if never_counted == NEVER_COUNTED_DUE_NOW:
        return anchor
    if never_counted == NEVER_COUNTED_UNSCHEDULED:
        return None
    raise ValueError(f"unknown never_counted policy {never_counted!r}")


def due_status(due: date | None, as_of: date, upcoming_days: int = 7) -> str:
    if due is None:
        return UNSCHEDULED
    if due < as_of:
        return OVERDUE
    if due == as_of:
        return DUE_TODAY
    if due <= as_of + timedelta(days=upcoming_days):
        return UPCOMING
    return SCHEDULED


def overdue_days(due: date | None, as_of: date) -> int:
    return max((as_of - due).days, 0) if due else 0


@dataclass(frozen=True)
class ScheduleItem:
    code: str
    action: str | None
    due: date | None
    never_counted: bool


def priority_key(it: ScheduleItem, as_of: date) -> tuple:
    """Most overdue first, then action urgency (CLOSE CONTROL first), then never-counted, then code."""
    due = it.due or date.max
    return (due, action_priority(it.action), not it.never_counted, it.code)
