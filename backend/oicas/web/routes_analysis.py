"""AMC / ABC / movement analysis, analysis runs, demand data, Reports Center and exports."""
from __future__ import annotations

import io
from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine.amc import Period
from ..engine.classification import MOVEMENT_CLASSES
from ..models import AnalysisResult, AnalysisRun, DemandBatch, User
from ..odoo.client import gateway_from_settings
from ..services import analysis, exports, importers, reports, sync
from .common import chart_json, redirect, render, report_page
from .deps import check_csrf, get_db, require

router = APIRouter()


def _month(v: str | None) -> date | None:
    try:
        y, m = map(int, (v or "").split("-")[:2])
        return date(y, m, 1)
    except ValueError:
        return None


@router.get("/analysis/amc", response_class=HTMLResponse)
def amc_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    runs = db.scalars(select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(20)).all()
    batches = db.scalars(select(DemandBatch).order_by(DemandBatch.id.desc()).limit(20)).all()
    return report_page(request, db, "amc", "amc", "Analysis", "AMC Analysis",
                       {"runs": runs, "batches": batches, "show_runs": True}, template="analysis_view.html")


@router.get("/analysis/abc", response_class=HTMLResponse)
def abc_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    run = analysis.current_run(db)
    if request.query_params.get("run_id"):
        run = db.get(AnalysisRun, int(request.query_params["run_id"]))
    chart = {}
    if run:
        cats = Counter(db.scalars(select(AnalysisResult.category).where(AnalysisResult.run_id == run.id,
                                                                        AnalysisResult.is_primary.is_(True))))
        chart = {"labels": sorted(cats), "values": [cats[k] for k in sorted(cats)]}
    return report_page(request, db, "abc", "abc", "Analysis", "ABC Analysis",
                       {"abc_chart": chart_json(chart), "run": run}, template="analysis_view.html")


@router.get("/analysis/movement", response_class=HTMLResponse)
def movement_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return report_page(request, db, "movement", "movement", "Analysis", "Movement Classification",
                       {"classes": MOVEMENT_CLASSES}, template="analysis_view.html")


@router.get("/analysis/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    run = db.get(AnalysisRun, run_id)
    if run is None:
        return render(request, db, "404.html", status_code=404, what=f"Analysis run #{run_id}")
    cur = analysis.current_run(db)
    diff = analysis.compare(db, cur.id, run.id) if cur and cur.id != run.id else []
    batch = db.get(DemandBatch, run.demand_batch_id) if run.demand_batch_id else None
    return render(request, db, "run_detail.html", active="amc", run=run, current=cur, diff=diff[:500],
                  diff_total=len(diff), batch=batch, period=Period(run.period_start, run.months))


@router.post("/analysis/runs", dependencies=[Depends(check_csrf)])
def run_create(batch_id: int = Form(...), start: str = Form(...), months: int = Form(...), notes: str = Form(""),
               db: Session = Depends(get_db), user: User = Depends(require("analysis.run"))):
    m = _month(start)
    if m is None or not 1 <= months <= 36:
        return redirect("/analysis/amc", "Enter a start month (YYYY-MM) and 1–36 months.", "danger")
    try:
        run = analysis.run_analysis(db, user, batch_id, Period(m, months), notes=notes or None)
    except (LookupError, ValueError) as e:
        db.rollback()
        return redirect("/analysis/amc", str(e), "danger")
    db.commit()
    return redirect(f"/analysis/runs/{run.id}", "Analysis calculated as a draft. Review the changes, then approve.")


@router.post("/analysis/runs/{run_id}/approve", dependencies=[Depends(check_csrf)])
def run_approve(run_id: int, db: Session = Depends(get_db), user: User = Depends(require("analysis.approve"))):
    try:
        analysis.approve(db, user, run_id)
    except (LookupError, ValueError) as e:
        db.rollback()
        return redirect(f"/analysis/runs/{run_id}", str(e), "danger")
    db.commit()
    return redirect(f"/analysis/runs/{run_id}", "Approved. Masterlist, schedule and dashboards now use this run.")


@router.post("/analysis/runs/{run_id}/reject", dependencies=[Depends(check_csrf)])
def run_reject(run_id: int, note: str = Form(""), db: Session = Depends(get_db),
               user: User = Depends(require("analysis.approve"))):
    try:
        analysis.reject(db, user, run_id, note)
    except ValueError as e:
        db.rollback()
        return redirect(f"/analysis/runs/{run_id}", str(e), "danger")
    db.commit()
    return redirect(f"/analysis/runs/{run_id}", "Run rejected.")


@router.post("/analysis/demand/upload", dependencies=[Depends(check_csrf)])
async def demand_upload(file: UploadFile = File(...), first_month: str = Form(""), db: Session = Depends(get_db),
                        user: User = Depends(require("import.run"))):
    data = await file.read()
    try:
        b = importers.upload_demand(db, user, io.BytesIO(data), file.filename or "demand.xlsx", _month(first_month))
    except Exception as e:
        db.rollback()
        return redirect("/analysis/amc", f"Demand upload failed: {e}", "danger")
    db.commit()
    return redirect("/analysis/amc", f"Demand batch #{b.id} imported ({b.line_count} item-months, "
                                     f"{b.period_start:%b %Y} – {b.period_end:%b %Y}).")


@router.post("/analysis/demand/sync", dependencies=[Depends(check_csrf)])
def demand_sync(start: str = Form(...), months: int = Form(...), db: Session = Depends(get_db),
                user: User = Depends(require("sync.run"))):
    m = _month(start)
    if m is None or not 1 <= months <= 36:
        return redirect("/analysis/amc", "Enter a start month (YYYY-MM) and 1–36 months.", "danger")
    try:
        run = sync.run_demand_sync(db, gateway_from_settings(), Period(m, months), user)
    except Exception as e:
        db.rollback()
        return redirect("/analysis/amc", f"Odoo demand sync could not start: {e}", "danger")
    db.commit()
    if run.status != "success":
        return redirect("/analysis/amc", f"Odoo demand sync failed: {run.error}", "danger")
    return redirect("/analysis/amc", f"Demand batch #{run.stats.get('demand_batch_id')} retrieved from Odoo "
                                     f"({run.stats.get('lines')} item-months).")


# ------------------------------------------------------------------ Reports Center
@router.get("/reports", response_class=HTMLResponse)
def reports_center(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    defs = sorted(reports.REGISTRY.values(), key=lambda d: d.number)
    return render(request, db, "reports.html", active="reports", defs=defs)


@router.get("/reports/{key}", response_class=HTMLResponse)
def report_view(key: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    if key not in reports.REGISTRY:
        return render(request, db, "404.html", status_code=404, what=f"Report {key}")
    if key == "audit_trail":
        from .. import security
        if not security.has_permission(user, "audit.view"):
            from .deps import Forbidden
            raise Forbidden("audit.view")
    return report_page(request, db, key, "reports", "Reports Center")


@router.get("/reports/{key}/export.{fmt}")
def report_export(key: str, fmt: str, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require("view"))):
    if key not in reports.REGISTRY or fmt not in ("xlsx", "pdf"):
        return Response("not found", status_code=404)
    if key == "audit_trail":
        from .. import security
        if not security.has_permission(user, "audit.view"):
            from .deps import Forbidden
            raise Forbidden("audit.view")
    rdef = reports.REGISTRY[key]
    params = {f.name: request.query_params.get(f.name) for f in rdef.filters if request.query_params.get(f.name)}
    res = reports.run(db, key, params)
    data, mime, name = exports.export(db, user, res, fmt, params)
    db.commit()
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})
