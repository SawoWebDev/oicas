"""FastAPI application: middleware, auth pages, dashboard, error handling."""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import security
from ..config import get_settings
from ..engine import metrics
from ..engine.classification import MOVEMENT_CLASSES
from ..models import AuditLog, Reconciliation, User
from ..odoo.client import gateway_from_settings
from ..services import auth, dq, inventory, rules
from . import common
from .common import BASE, chart_json, redirect, render
from .deps import COOKIE, CsrfFailed, Forbidden, NotAuthenticated, client_ip, current_user, get_db, require

log = logging.getLogger("oicas.web")
settings = get_settings()

app = FastAPI(title="OICAS", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if not request.url.path.startswith("/static"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(NotAuthenticated)
async def _unauth(request: Request, exc):
    if request.headers.get("HX-Request"):
        return HTMLResponse("", status_code=401, headers={"HX-Redirect": "/login"})
    nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={nxt}", status_code=303)


@app.exception_handler(Forbidden)
async def _forbidden(request: Request, exc: Forbidden):
    return render(request, None, "403.html", status_code=403, perm=exc.perm)


@app.exception_handler(CsrfFailed)
async def _csrf(request: Request, exc):
    return render(request, None, "403.html", status_code=403, perm="valid form token (reload the page and try again)")


# ------------------------------------------------------------------ auth
def _safe_next(n: str | None) -> str:
    return n if n and n.startswith("/") and not n.startswith("//") else "/"


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return render(request, None, "login.html", next=_safe_next(next), error=None, login="")


@app.post("/login")
def login_submit(request: Request, login: str = Form(""), password: str = Form(""), next: str = Form("/"),
                 method: str = Form("odoo"), db: Session = Depends(get_db)):
    try:
        if method == "local":
            _, token = auth.login_local(db, login, password, client_ip(request), request.headers.get("user-agent"))
        else:
            _, token = auth.login_with_odoo(db, gateway_from_settings(), login, password, client_ip(request),
                                            request.headers.get("user-agent"))
    except auth.AuthError as e:
        db.commit()
        return render(request, None, "login.html", status_code=401, next=_safe_next(next), error=str(e), login=login)
    db.commit()
    resp = RedirectResponse(_safe_next(next), status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                    max_age=settings.session_hours * 3600)
    return resp


@app.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    sess = security.load_session(db, request.cookies.get(COOKIE))
    if sess:
        from ..services import audit
        audit.record(db, sess.user, "auth.logout", "app_user", sess.user_id, {}, client_ip(request))
    security.revoke_session(db, request.cookies.get(COOKIE))
    db.commit()
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    return JSONResponse({"status": "ok", "odoo_mode": settings.odoo_mode})


# ------------------------------------------------------------------ dashboard
DASH_FILTERS = ("material_section", "abc_family", "plant_location")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    f = common.form_params(request, DASH_FILTERS)
    ds = inventory.build(db)
    rows = inventory.apply_filters(ds.rows, f)
    kpis = inventory.overall_kpis(rows)
    total = metrics.total_of(kpis)
    due = Counter(r.due_status for r in rows)
    end = date.today()
    start = end - timedelta(weeks=8)
    weekly = inventory.weekly_kpis(db, rows, start, end)
    weeks = [w.week_label for w in weekly[MOVEMENT_CLASSES[0]]]
    week_counted = [sum(weekly[c][i].total_counted for c in MOVEMENT_CLASSES) for i in range(len(weeks))]
    week_disc = [sum(weekly[c][i].discrepancy for c in MOVEMENT_CLASSES) for i in range(len(weeks))]
    week_unver = [sum(weekly[c][i].unverified for c in MOVEMENT_CLASSES) for i in range(len(weeks))]
    week_acc = [metrics.ratio(a - u - b, a - u) for a, b, u in zip(week_counted, week_disc, week_unver)]
    cats = Counter(r.category for r in rows if r.category)
    by_plant: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        p = r.plant_location or "(none)"
        by_plant[p][0] += 1
        by_plant[p][1] += int(r.counted)
    tracked = {r.code for r in rows}
    by_counter = Counter()
    for rc in db.scalars(select(Reconciliation).where(Reconciliation.superseded.is_(False),
                                                      Reconciliation.count_date >= end - timedelta(days=30))):
        if rc.item_code in tracked:
            for who in (rc.counted_by or "Unknown").split(", "):
                by_counter[who] += 1
    recent = db.scalars(select(AuditLog).where(~AuditLog.action.like("auth.%"), AuditLog.action != "report.export")
                        .order_by(AuditLog.at.desc()).limit(8)).all()
    charts = {
        "classes": {"labels": list(MOVEMENT_CLASSES),
                    "completion": [kpis[c].completion for c in MOVEMENT_CLASSES],
                    "accuracy": [kpis[c].accuracy for c in MOVEMENT_CLASSES],
                    "overall_accuracy": [kpis[c].overall_accuracy for c in MOVEMENT_CLASSES],
                    "discrepancy_rate": [kpis[c].discrepancy_rate for c in MOVEMENT_CLASSES]},
        "weekly": {"labels": weeks, "counted": week_counted, "discrepancy": week_disc, "accuracy": week_acc},
        "abc": {"labels": sorted(cats), "values": [cats[k] for k in sorted(cats)]},
    }
    from urllib.parse import urlencode
    return render(request, db, "dashboard.html", active="dashboard", kpis=kpis, total=total, due=due, f=f, fq=urlencode(f),
                  options={k: rules.get_setting(db, {"material_section": "material_sections", "abc_family": "abc_families",
                                                     "plant_location": "plant_locations"}[k]) for k in DASH_FILTERS},
                  charts=chart_json(charts), by_plant=sorted(by_plant.items()), by_counter=by_counter.most_common(8),
                  dq_kinds=sorted(dq.open_counts(db).items(), key=lambda kv: -kv[1])[:6], recent=recent,
                  run_period=ds.run_period, run_id=ds.run_id, classes=MOVEMENT_CLASSES)


from . import routes_admin, routes_analysis, routes_inventory  # noqa: E402

app.include_router(routes_inventory.router)
app.include_router(routes_analysis.router)
app.include_router(routes_admin.router)

problems = settings.check_production_safety()
if problems:
    for p in problems:
        log.error("UNSAFE PRODUCTION CONFIGURATION: %s", p)
    if settings.is_production:
        raise RuntimeError("refusing to start: " + "; ".join(problems))

__all__ = ["app", "current_user"]
