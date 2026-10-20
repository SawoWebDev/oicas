"""Versioned calculation rule sets and non-calculation application settings."""
from __future__ import annotations

import copy
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..engine import abc, classification, reconciliation, scheduling
from ..engine.amc import AMC_PERIOD_MONTHS, AMC_RECORDED_MONTHS
from ..models import AppSetting, RuleSet, User
from . import audit

DEFAULT_PARAMS: dict = {
    "abc": {"qty_a_below": 0.80, "qty_c_from": 0.95, "freq_a_above": 0.80, "freq_c_upto": 0.50,
            "ordering": abc.ORDER_DEMAND_DESC},
    "amc": {"method": AMC_RECORDED_MONTHS},
    "reconciliation": {"abs_tolerance": 0.0, "uncounted_bucket": reconciliation.UNCOUNTED_AS_MISSING,
                       "missing_odoo": reconciliation.ODOO_MISSING_AS_MISSING},
    "schedule": {"never_counted": scheduling.NEVER_COUNTED_DUE_NOW, "upcoming_days": 7},
}

DEFAULT_SETTINGS: dict = {
    "material_sections": ["RAW MAT", "BOX", "Metal Stamping", "Pre-Assy", "Stone", "T&D", "PIM", "Control Unit",
                          "Wood", "SF Wood", "Innova", "Consumables", "Expensive WH", "Central WH", "Electrical WH"],
    "abc_families": ["RAW MAT", "BOX", "Metal Stamping", "Pre-Assy", "Stone", "T&D", "PIM", "Control Unit", "Wood",
                     "SF Wood", "Excluded list"],
    "plant_locations": ["1", "2", "3", "4", "1 & 2", "1 & 3", "1 & 4", "2 & 3", "2 & 4", "3 & 4", "1 & 2 & 3",
                        "1 & 2 & 4", "1 & 3 & 4", "2 & 3 & 4", "1 & 2 & 3 & 4"],
    "count_slots": ["1", "2", "3", "4"],
    # Odoo group XML id -> OICAS role (highest match wins). Unmatched internal users get default_role.
    "auth_group_role_map": {"base.group_system": "admin", "stock.group_stock_manager": "manager",
                            "stock.group_stock_user": "counter"},
    "auth_default_role": "viewer",
    "odoo_stale_after_hours": 24,
    "odoo_demand_exclude_cancelled": True,
    "snapshot_retention_days": 400,
}


def validate_params(params: dict, matrix: dict) -> None:
    abc.AbcParams.from_dict(params["abc"]).validate()
    if params["amc"]["method"] not in (AMC_RECORDED_MONTHS, AMC_PERIOD_MONTHS):
        raise ValueError("amc.method must be recorded_months or period_months")
    r = params["reconciliation"]
    if float(r["abs_tolerance"]) < 0:
        raise ValueError("reconciliation.abs_tolerance must be >= 0")
    if r["uncounted_bucket"] not in (reconciliation.UNCOUNTED_AS_MISSING, reconciliation.UNCOUNTED_AS_ZERO):
        raise ValueError("reconciliation.uncounted_bucket must be not_counted or zero")
    if r["missing_odoo"] not in (reconciliation.ODOO_MISSING_AS_MISSING, reconciliation.ODOO_MISSING_AS_ZERO):
        raise ValueError("reconciliation.missing_odoo must be missing or zero")
    sch = params["schedule"]
    if sch["never_counted"] not in (scheduling.NEVER_COUNTED_DUE_NOW, scheduling.NEVER_COUNTED_UNSCHEDULED):
        raise ValueError("schedule.never_counted must be due_now or unscheduled")
    if int(sch["upcoming_days"]) < 0:
        raise ValueError("schedule.upcoming_days must be >= 0")
    classification.validate_matrix(matrix)


def merged_params(stored: dict) -> dict:
    out = copy.deepcopy(DEFAULT_PARAMS)
    for k, v in (stored or {}).items():
        if isinstance(v, dict) and k in out:
            out[k].update(v)
        else:
            out[k] = v
    return out


def active_rule_set(db: Session, on: date | None = None) -> RuleSet:
    on = on or date.today()
    rs = db.scalars(select(RuleSet).where(RuleSet.effective_from <= on)
                    .order_by(RuleSet.effective_from.desc(), RuleSet.version.desc())).first()
    if rs is None:
        rs = db.scalars(select(RuleSet).order_by(RuleSet.version)).first()
    if rs is None:
        rs = ensure_default_rule_set(db)
    return rs


def params_of(rs: RuleSet) -> dict:
    return merged_params(rs.params)


def ensure_default_rule_set(db: Session) -> RuleSet:
    rs = db.scalars(select(RuleSet).where(RuleSet.version == 1)).first()
    if rs is None:
        rs = RuleSet(version=1, name="Legacy rules 2025-26 (verified from workbooks)", effective_from=date(2025, 9, 1),
                     params=copy.deepcopy(DEFAULT_PARAMS), class_matrix=copy.deepcopy(classification.DEFAULT_CLASS_MATRIX),
                     notes="Seeded from CLASS sheet and family-sheet formulas. See docs/analysis/03-formula-register.md.")
        db.add(rs)
        db.flush()
    return rs


def create_rule_set(db: Session, user: User, name: str, effective_from: date, params: dict, matrix: dict,
                    notes: str | None) -> RuleSet:
    params = merged_params(params)
    validate_params(params, matrix)
    version = (db.scalar(select(func.max(RuleSet.version))) or 0) + 1
    rs = RuleSet(version=version, name=name, effective_from=effective_from, params=params, class_matrix=matrix,
                 notes=notes, created_by_id=user.id)
    db.add(rs)
    db.flush()
    audit.record(db, user, "ruleset.create", "rule_set", rs.id,
                 {"version": version, "effective_from": effective_from, "params": params, "matrix": matrix})
    return rs


# ------------------------------------------------------------------ app settings
def get_setting(db: Session, key: str):
    row = db.get(AppSetting, key)
    if row is None:
        return copy.deepcopy(DEFAULT_SETTINGS.get(key))
    return row.value


def set_setting(db: Session, user: User | None, key: str, value) -> None:
    if key not in DEFAULT_SETTINGS:
        raise KeyError(f"unknown setting {key}")
    row = db.get(AppSetting, key)
    before = row.value if row else DEFAULT_SETTINGS[key]
    if row is None:
        row = AppSetting(key=key, value=value, updated_by_id=user.id if user else None)
        db.add(row)
    else:
        row.value = value
        row.updated_by_id = user.id if user else None
    audit.record(db, user, "setting.update", "app_setting", key, {"before": before, "after": value})
