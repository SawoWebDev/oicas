"""Data quality, synchronization history, audit trail and System Configuration."""
from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import security
from ..engine.reconciliation import BUCKETS
from ..models import RuleSet, StockLocation, User
from ..services import audit, dq, importers, rules, sync
from .common import redirect, render, report_page
from .deps import check_csrf, client_ip, get_db, require

router = APIRouter()


# ------------------------------------------------------------------ data quality
@router.get("/data-quality", response_class=HTMLResponse)
def dq_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return report_page(request, db, "data_quality", "dq", "Governance", "Data Quality",
                       {"counts": sorted(dq.open_counts(db).items(), key=lambda kv: -kv[1]), "kinds": dq.KINDS},
                       template="dq.html")


@router.post("/data-quality/scan", dependencies=[Depends(check_csrf)])
def dq_scan(db: Session = Depends(get_db), user: User = Depends(require("dq.resolve"))):
    res = dq.scan_items(db)
    audit.record(db, user, "dq.scan", None, None, res)
    db.commit()
    return redirect("/data-quality", "Masterlist checks re-run: " + ", ".join(f"{k} {v}" for k, v in res.items()))


@router.post("/data-quality/{exc_id}", dependencies=[Depends(check_csrf)])
def dq_status(exc_id: int, status: str = Form(...), note: str = Form(""), db: Session = Depends(get_db),
              user: User = Depends(require("dq.resolve"))):
    try:
        dq.set_status(db, user, exc_id, status, note)
    except (LookupError, ValueError) as e:
        db.rollback()
        return redirect("/data-quality", str(e), "danger")
    db.commit()
    return redirect("/data-quality", f"Exception marked {status}.")


# ------------------------------------------------------------------ sync
@router.get("/sync", response_class=HTMLResponse)
def sync_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return report_page(request, db, "sync_history", "sync", "Governance", "Synchronization History",
                       template="sync.html")


@router.post("/sync/run", dependencies=[Depends(check_csrf)])
def sync_run(request: Request, erp_password: str = Form(""), db: Session = Depends(get_db),
             user: User = Depends(require("sync.run"))):
    from ..services.auth import AuthError
    from .common import NeedErpPassword, erp_gateway
    try:
        gw = erp_gateway(request, user, erp_password or None)
        run = sync.run_inventory_sync(db, gw, user)
    except NeedErpPassword:
        return redirect("/sync", "Enter your ERP password to sync with your Odoo account.", "warning")
    except AuthError as e:
        return redirect("/sync", str(e), "danger")
    except Exception as e:  # configuration errors (e.g. missing ODOO_URL)
        db.rollback()
        return redirect("/sync", f"Sync could not start: {e}", "danger")
    db.commit()
    if run.status == "success":
        return redirect("/sync", f"Odoo sync #{run.id} succeeded: snapshot #{run.stats.get('snapshot_id')}, "
                                 f"{run.stats.get('products')} products, {run.stats.get('quants')} quants.")
    return redirect("/sync", f"Odoo sync #{run.id} failed: {run.error}. Cached data is unchanged.", "danger")


# ------------------------------------------------------------------ audit
@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("audit.view"))):
    return report_page(request, db, "audit_trail", "audit", "Governance", "Audit Trail")


# ------------------------------------------------------------------ configuration
@router.get("/config", response_class=HTMLResponse)
def config_page(request: Request, tab: str = "rules", db: Session = Depends(get_db),
                user: User = Depends(require("config.manage"))):
    rs_all = db.scalars(select(RuleSet).order_by(RuleSet.version.desc())).all()
    active = rules.active_rule_set(db)
    settings_view = {k: rules.get_setting(db, k) for k in rules.DEFAULT_SETTINGS}
    locs = db.scalars(select(StockLocation).order_by(StockLocation.complete_name)).all()
    users = db.scalars(select(User).order_by(User.login)).all()
    from ..models import SyncRun
    imports = db.scalars(select(SyncRun).where(SyncRun.kind == "import").order_by(SyncRun.id.desc())).all()
    ref_dir = Path(__file__).resolve().parents[3] / "docs" / "reference"
    return render(request, db, "config.html", active="config", tab=tab, rule_sets=rs_all, active_rs=active,
                  active_params=rules.params_of(active), settings_view=settings_view, locs=locs, buckets=BUCKETS,
                  users=users, roles=security.ROLES, imports=imports, ref_available=ref_dir.exists(),
                  sessions=security.active_sessions(db), json=json)


@router.post("/config/rulesets", dependencies=[Depends(check_csrf)])
async def ruleset_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("config.manage"))):
    f = await request.form()
    try:
        params = {
            "abc": {"qty_a_below": float(f["qty_a_below"]) / 100, "qty_c_from": float(f["qty_c_from"]) / 100,
                    "freq_a_above": float(f["freq_a_above"]) / 100, "freq_c_upto": float(f["freq_c_upto"]) / 100,
                    "ordering": f["ordering"]},
            "amc": {"method": f["amc_method"]},
            "reconciliation": {"abs_tolerance": float(f["abs_tolerance"]), "uncounted_bucket": f["uncounted_bucket"],
                               "missing_odoo": f["missing_odoo"]},
            "schedule": {"never_counted": f["never_counted"], "upcoming_days": int(f["upcoming_days"])},
        }
        matrix = json.loads(f["class_matrix"])
        eff = date.fromisoformat(f["effective_from"])
        if not (f.get("name") or "").strip():
            raise ValueError("give the rule set a name")
        rs = rules.create_rule_set(db, user, f["name"].strip(), eff, params, matrix, f.get("notes") or None)
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        db.rollback()
        return redirect("/config?tab=rules", f"Rule set not saved: {e}", "danger")
    db.commit()
    return redirect("/config?tab=rules", f"Rule set version {rs.version} saved, effective {rs.effective_from}. "
                                         "Existing analysis runs and reconciliations keep their original version.")


@router.post("/config/settings", dependencies=[Depends(check_csrf)])
async def settings_save(request: Request, db: Session = Depends(get_db), user: User = Depends(require("config.manage"))):
    f = await request.form()
    key = f.get("key")
    raw = f.get("value", "")
    try:
        default = rules.DEFAULT_SETTINGS[key]
        if isinstance(default, list):
            value = [x.strip() for x in raw.splitlines() if x.strip()]
        elif isinstance(default, dict):
            value = json.loads(raw)
            if key == "auth_group_role_map" and any(v not in security.ROLES for v in value.values()):
                raise ValueError(f"roles must be one of {security.ROLES}")
        elif isinstance(default, bool):
            value = raw in ("1", "true", "on", "yes")
        elif isinstance(default, int):
            value = int(raw)
            if value < 0:
                raise ValueError("must be zero or positive")
        else:
            value = raw.strip()
            if key == "auth_default_role" and value not in ("", *security.ROLES):
                raise ValueError("unknown role")
            value = value or None
        rules.set_setting(db, user, key, value)
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        db.rollback()
        return redirect("/config?tab=settings", f"Setting not saved: {e}", "danger")
    db.commit()
    return redirect("/config?tab=settings", f"Setting {key} saved.")


@router.post("/config/locations", dependencies=[Depends(check_csrf)])
async def locations_save(request: Request, db: Session = Depends(get_db), user: User = Depends(require("config.manage"))):
    f = await request.form()
    changes = {}
    for loc in db.scalars(select(StockLocation)):
        v = f.get(f"bucket_{loc.id}")
        if v is None:
            continue
        v = v or None
        if v not in (None, "IGNORE", *BUCKETS):
            continue
        if loc.bucket != v:
            changes[loc.complete_name] = [loc.bucket, v]
            loc.bucket = v
    audit.record(db, user, "config.locations", "stock_location", None, {"changes": changes}, client_ip(request))
    db.commit()
    return redirect("/config?tab=locations", f"{len(changes)} location mapping(s) updated. They apply from the next "
                                             "Odoo sync; earlier snapshots are unchanged.")


@router.post("/config/users/{uid}", dependencies=[Depends(check_csrf)])
def user_update(uid: int, request: Request, role: str = Form(...), active: str = Form(""), role_locked: str = Form(""),
                db: Session = Depends(get_db), admin: User = Depends(require("users.manage"))):
    u = db.get(User, uid)
    if u is None or role not in security.ROLES:
        return redirect("/config?tab=users", "Unknown user or role.", "danger")
    if u.id == admin.id and (role != "admin" or not active):
        return redirect("/config?tab=users", "You can't remove your own administrator access.", "danger")
    before = {"role": u.role, "active": u.active, "role_locked": u.role_locked}
    u.role, u.active, u.role_locked = role, bool(active), bool(role_locked)
    if not u.active:
        security.revoke_user_sessions(db, u.id)
    audit.record(db, admin, "user.update", "app_user", u.id,
                 {"before": before, "after": {"role": role, "active": u.active, "role_locked": u.role_locked}},
                 client_ip(request))
    db.commit()
    return redirect("/config?tab=users", f"{u.login} updated.")


@router.post("/config/sessions/{uid}/revoke", dependencies=[Depends(check_csrf)])
def sessions_revoke(uid: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require("users.manage"))):
    security.revoke_user_sessions(db, uid)
    audit.record(db, admin, "user.sessions_revoked", "app_user", uid, {}, client_ip(request))
    db.commit()
    return redirect("/config?tab=users", "Sessions revoked.")


@router.post("/config/import/legacy", dependencies=[Depends(check_csrf)])
def import_legacy(db: Session = Depends(get_db), user: User = Depends(require("config.manage"))):
    ref = Path(__file__).resolve().parents[3] / "docs" / "reference"
    try:
        runs = importers.import_reference_set(db, user, ref)
    except importers.ImportError_ as e:
        db.rollback()
        return redirect("/config?tab=imports", str(e), "danger")
    db.commit()
    return redirect("/config?tab=imports", "Legacy workbooks migrated: " + "; ".join(
        f"{r.scope['type']} #{r.id}" for r in runs))


@router.post("/config/import/items", dependencies=[Depends(check_csrf)])
async def import_items(file: UploadFile = File(...), db: Session = Depends(get_db),
                       user: User = Depends(require("item.edit"))):
    data = await file.read()
    try:
        n, errors = importers.upload_item_attributes(db, user, io.BytesIO(data))
    except Exception as e:
        db.rollback()
        return redirect("/config?tab=imports", f"Could not read the file: {e}", "danger")
    db.commit()
    msg = f"{n} item(s) updated." + (f" {len(errors)} row(s) rejected: " + "; ".join(errors[:5]) if errors else "")
    return redirect("/config?tab=imports", msg, "warning" if errors else "success")
