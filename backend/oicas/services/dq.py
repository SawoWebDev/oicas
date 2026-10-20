"""Data-quality exceptions (docs/analysis/09-data-quality-register.md).

Problems are flagged, never silently corrected. Detectors upsert by (kind, ref) and auto-resolve
exceptions of the same kind/source that are no longer observed.
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DqException, Item, User, utcnow
from . import audit

KINDS: dict[str, str] = {
    "unmapped_location": "Odoo internal location not mapped to WAREHOUSE / PRODUCTION",
    "product_without_code": "Odoo product has no Internal Reference (default_code)",
    "duplicate_product_code": "Several Odoo products share one Internal Reference",
    "product_code_changed": "Odoo product's Internal Reference differs from the OICAS item code",
    "missing_uom": "Item has no unit of measure",
    "negative_odoo_qty": "Odoo on-hand quantity is negative",
    "unknown_item_code": "Code used in counts/demand/import is not a known item",
    "duplicate_code_family": "Item code belongs to more than one ABC family",
    "missing_plant_location": "Tracked item has no plant location",
    "missing_material_section": "Tracked item has no material section",
    "missing_family": "Tracked item has no ABC family",
    "odoo_balance_missing": "No Odoo balance available for a counted item",
    "stale_snapshot": "Latest Odoo snapshot is older than the staleness threshold",
    "duplicate_count_line": "Same item counted more than once on the same date by the same import",
    "count_line_without_qty": "Imported count line has an item and date but no quantity",
    "unknown_classification": "ABC category not found in the classification matrix",
    "sync_failed": "Odoo synchronisation failed",
    "uom_variant": "Unit of measure spelled differently from its canonical form",
}


def flag(db: Session, kind: str, ref: str, detail: str = "", severity: str = "warning", source: str = "") -> None:
    if kind not in KINDS:
        raise KeyError(kind)
    row = db.scalars(select(DqException).where(DqException.kind == kind, DqException.ref == ref)).first()
    now = utcnow()
    if row is None:
        db.add(DqException(kind=kind, ref=ref, detail=detail, severity=severity, source=source, first_seen_at=now,
                           last_seen_at=now))
    else:
        row.detail, row.severity, row.last_seen_at, row.source = detail, severity, now, source or row.source
        if row.status == "resolved":
            row.status, row.resolved_at, row.resolved_by_id = "open", None, None


def auto_resolve(db: Session, kind: str, still_present: set[str], source: str | None = None) -> int:
    q = select(DqException).where(DqException.kind == kind, DqException.status == "open")
    if source:
        q = q.where(DqException.source == source)
    n = 0
    for row in db.scalars(q):
        if row.ref not in still_present:
            row.status, row.resolved_at = "resolved", utcnow()
            n += 1
    return n


def set_status(db: Session, user: User, exc_id: int, status: str, note: str = "") -> DqException:
    if status not in ("open", "resolved", "ignored"):
        raise ValueError("invalid status")
    row = db.get(DqException, exc_id)
    if row is None:
        raise LookupError("exception not found")
    before = row.status
    row.status = status
    row.resolved_at = utcnow() if status != "open" else None
    row.resolved_by_id = user.id if status != "open" else None
    audit.record(db, user, "dq.status", "dq_exception", exc_id, {"before": before, "after": status, "note": note})
    return row


def scan_items(db: Session) -> dict[str, int]:
    """Masterlist attribute checks (DQ-13, DQ-15, DQ-16, DQ-03)."""
    from ..models import ItemFamily
    found: dict[str, set[str]] = {k: set() for k in ("missing_uom", "missing_plant_location",
                                                    "missing_material_section", "missing_family",
                                                    "duplicate_code_family")}
    for it in db.scalars(select(Item).where(Item.tracked.is_(True))):
        if not it.uom_name:
            found["missing_uom"].add(it.code)
        if not it.plant_location or it.plant_location == "0":
            found["missing_plant_location"].add(it.code)
        if not it.material_section or it.material_section == "0":
            found["missing_material_section"].add(it.code)
        if not it.abc_family:
            found["missing_family"].add(it.code)
    fam = Counter(db.scalars(select(ItemFamily.item_code)))
    found["duplicate_code_family"] = {c for c, n in fam.items() if n > 1}
    for kind, refs in found.items():
        for ref in refs:
            flag(db, kind, ref, KINDS[kind], "info" if kind == "missing_plant_location" else "warning", "item_scan")
        auto_resolve(db, kind, refs, "item_scan")
    return {k: len(v) for k, v in found.items()}


def open_counts(db: Session) -> dict[str, int]:
    return dict(db.execute(select(DqException.kind, func.count()).where(DqException.status == "open")
                           .group_by(DqException.kind)).all())
