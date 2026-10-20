"""Category → declared inventory type / action / movement classification / count interval.

Legacy source: CLASS sheet H5:L13 + G (days), family sheets Y, Z, AA; CONSOLIDATED AE/AF
(docs/analysis/03-formula-register.md F-12, F-14; BR-11..BR-13).
"""
from __future__ import annotations

from dataclasses import dataclass

FAST, MEDIUM, SLOW, NON = "Fast Moving", "Medium Moving", "Slow Moving", "Non Moving"
MOVEMENT_CLASSES = (FAST, MEDIUM, SLOW, NON)
ACTIONS = ("CLOSE CONTROL", "REGULAR REVIEW", "INFREQUENT REVIEW")

# Seeded as rule set v1 (CLASS sheet rows 5-13).
DEFAULT_CLASS_MATRIX: dict[str, dict] = {
    "AA": {"declared_type": "MTS", "action": "CLOSE CONTROL", "classification": FAST, "interval_days": 30},
    "AB": {"declared_type": "MTS", "action": "CLOSE CONTROL", "classification": FAST, "interval_days": 30},
    "BA": {"declared_type": "MTS", "action": "CLOSE CONTROL", "classification": FAST, "interval_days": 30},
    "BB": {"declared_type": "MTS", "action": "REGULAR REVIEW", "classification": MEDIUM, "interval_days": 90},
    "CA": {"declared_type": "MTS", "action": "REGULAR REVIEW", "classification": MEDIUM, "interval_days": 90},
    "AC": {"declared_type": "MTS", "action": "REGULAR REVIEW", "classification": MEDIUM, "interval_days": 90},
    "BC": {"declared_type": "MTO", "action": "INFREQUENT REVIEW", "classification": SLOW, "interval_days": 180},
    "CB": {"declared_type": "MTO", "action": "INFREQUENT REVIEW", "classification": SLOW, "interval_days": 180},
    "CC": {"declared_type": "MTO", "action": "INFREQUENT REVIEW", "classification": SLOW, "interval_days": 180},
}


@dataclass(frozen=True)
class Classification:
    category: str
    declared_type: str | None
    action: str | None
    classification: str | None
    interval_days: int | None

    @property
    def interval_key(self) -> str:
        """CONSOLIDATED!AE ``=X&Y`` (e.g. ``ABMTS``)."""
        return f"{self.category}{self.declared_type or ''}"

    @property
    def found(self) -> bool:
        return self.action is not None


def validate_matrix(matrix: dict[str, dict]) -> None:
    for cat, row in matrix.items():
        if len(cat) != 2 or any(c not in "ABC" for c in cat):
            raise ValueError(f"invalid category {cat!r}")
        if row.get("classification") not in (FAST, MEDIUM, SLOW):
            raise ValueError(f"{cat}: classification must be Fast/Medium/Slow Moving")
        if row.get("action") not in ACTIONS:
            raise ValueError(f"{cat}: unknown action {row.get('action')!r}")
        days = row.get("interval_days")
        if not isinstance(days, int) or days <= 0:
            raise ValueError(f"{cat}: interval_days must be a positive integer")


def classify(category: str, frequency: int, matrix: dict[str, dict] | None = None) -> Classification:
    """``AA = IF(R=0,"Non Moving",VLOOKUP(X,CLASS,4))``; Y/Z/AF from the same row.

    An unknown category returns ``found == False`` (Excel would show #N/A / "- Not Found").
    """
    m = matrix or DEFAULT_CLASS_MATRIX
    row = m.get(category)
    if row is None:
        return Classification(category, None, None, NON if frequency == 0 else None, None)
    cls = NON if frequency == 0 else row["classification"]
    return Classification(category, row["declared_type"], row["action"], cls, int(row["interval_days"]))


def action_priority(action: str | None) -> int:
    """Lower = more urgent. Used for scheduling order."""
    try:
        return ACTIONS.index(action)  # type: ignore[arg-type]
    except ValueError:
        return len(ACTIONS)
