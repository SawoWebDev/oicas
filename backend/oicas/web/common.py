"""Shared web helpers: templates, flash messages, pagination, report-table rendering."""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from .. import __version__, security
from ..config import get_settings
from ..services import dq, sync
from ..services.exports import fmt

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


def _static_version() -> str:
    """Fingerprint of our own CSS/JS: appended as ?v=… so browsers fetch new files after an update."""
    import hashlib
    h = hashlib.sha256()
    for rel in ("css/gas-base.css", "css/app.css", "js/app.js", "js/annual.js", "js/amc_import.js", "js/planning.js"):
        p = BASE / "static" / rel
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:10]


STATIC_V = _static_version()
FLASH = "oicas_flash"

NAV = [
    ("Overview", [("dashboard", "/", "bi-grid", "Dashboard", "view"),
                  ("help", "/help", "bi-question-circle", "Help Center (F1)", "view")]),
    ("Inventory", [
        ("masterlist", "/masterlist", "bi-list-ul", "Inventory Masterlist", "view"),
        ("planning", "/planning", "bi-calendar2-check", "Cycle Count Planning", "view"),
        ("counting", "/counting", "bi-clipboard-check", "Physical Counting", "count.enter"),
        ("annual", "/annual-inventory", "bi-journal-check", "Annual Inventory", "count.enter"),
        ("history", "/history", "bi-clock-history", "Count History", "view"),
        ("reconciliation", "/reconciliation", "bi-arrow-left-right", "Odoo Reconciliation", "view"),
        ("imports", "/imports", "bi-upload", "Data Import", "import.run"),
    ]),
    ("Analysis", [
        ("amc_import", "/amc-import", "bi-file-earmark-spreadsheet", "AMC Import", "view"),
        ("amc", "/analysis/amc", "bi-graph-up", "AMC Analysis", "view"),
        ("abc", "/analysis/abc", "bi-bar-chart-steps", "ABC Analysis", "view"),
        ("movement", "/analysis/movement", "bi-speedometer2", "Movement Classification", "view"),
        ("reports", "/reports", "bi-file-earmark-bar-graph", "Reports Center", "view"),
    ]),
    ("Governance", [
        ("dq", "/data-quality", "bi-exclamation-diamond", "Data Quality", "view"),
        ("sync", "/sync", "bi-arrow-repeat", "Synchronization History", "view"),
        ("audit", "/audit", "bi-shield-check", "Audit Trail", "audit.view"),
        ("config", "/config", "bi-gear", "System Configuration", "config.manage"),
    ]),
]

PILL_TONES = {
    "Fast Moving": "tone-green", "Medium Moving": "tone-blue", "Slow Moving": "tone-orange", "Non Moving": "tone-gray",
    "CLOSE CONTROL": "tone-green", "REGULAR REVIEW": "tone-yellow", "INFREQUENT REVIEW": "tone-red",
    "overdue": "tone-red", "due_today": "tone-orange", "upcoming": "tone-yellow", "scheduled": "tone-blue",
    "unscheduled": "tone-gray", "accurate": "tone-green", "discrepancy": "tone-red", "odoo_missing": "tone-orange",
    "not_counted": "tone-gray", "open": "tone-red", "investigating": "tone-orange", "recount_requested": "tone-purple",
    "resolved": "tone-green", "n_a": "tone-gray", "draft": "tone-gray", "submitted": "tone-blue", "finalized": "tone-green",
    "cancelled": "tone-gray", "approved": "tone-green", "superseded": "tone-gray", "rejected": "tone-red",
    "success": "tone-green", "failed": "tone-red", "running": "tone-blue", "partial": "tone-orange", "closed": "tone-gray",
    "error": "tone-red", "warning": "tone-orange", "info": "tone-blue", "ignored": "tone-gray",
    "A": "tone-green", "B": "tone-yellow", "C": "tone-red", "pending": "tone-gray", "counted": "tone-green",
}
PILL_KEYS = {"classification", "action", "due_status", "recon_status", "status", "review_status", "severity",
             "qty_class", "freq_class", "run_status", "state"}


def _signer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="flash")


def flash(resp, message: str, level: str = "success", undo: str | None = None):
    """Queue a toast for the next page. ``undo`` is a POST URL; the toast then shows an Undo button that calls it."""
    payload = [level, message] + ([undo] if undo else [])
    resp.set_cookie(FLASH, _signer().dumps(payload), max_age=60, httponly=True, samesite="lax",
                    secure=get_settings().cookie_secure)
    return resp


def redirect(url: str, message: str | None = None, level: str = "success", undo: str | None = None) -> RedirectResponse:
    resp = RedirectResponse(url, status_code=303)
    if message:
        flash(resp, message, level, undo)
    return resp


def humanize(v: str | None) -> str:
    if v == "n_a":
        return "n/a"
    return (v or "").replace("_", " ")


def pill(value, key: str | None = None) -> str:
    from markupsafe import Markup, escape
    if value in (None, ""):
        return Markup('<span class="muted">–</span>')
    tone = PILL_TONES.get(str(value), "tone-gray")
    return Markup(f'<span class="pill pill-sm {tone}">{escape(humanize(str(value)))}</span>')


def cell(row: dict, col) -> str:
    from markupsafe import Markup, escape
    v = row.get(col.key)
    if col.key in PILL_KEYS and isinstance(v, str):
        return pill(v)
    text = fmt(v, col.kind)
    if col.kind in ("qty", "int", "pct") and isinstance(v, (int, float)) and not isinstance(v, bool):
        cls = "num neg" if v < 0 else "num"
        return Markup(f'<span class="{cls}">{escape(text)}</span>')
    return Markup(escape(text)) if text != "–" else Markup('<span class="muted">–</span>')


def query(request: Request, **changes) -> str:
    params = dict(request.query_params)
    for k, v in changes.items():
        if v is None:
            params.pop(k, None)
        else:
            params[k] = v
    return "?" + urlencode(params)


def paginate(rows: list, request: Request, per_page: int = 50) -> dict:
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        page = 1
    pages = max(1, math.ceil(len(rows) / per_page))
    page = min(page, pages)
    start = (page - 1) * per_page
    return {"rows": rows[start:start + per_page], "page": page, "pages": pages, "count": len(rows),
            "start": start + 1 if rows else 0, "end": min(start + per_page, len(rows))}


def sort_rows(rows: list[dict], request: Request, columns) -> list[dict]:
    key = request.query_params.get("sort")
    if not key or key not in {c.key for c in columns}:
        return rows
    desc = request.query_params.get("dir") == "desc"

    def k(r):
        v = r.get(key)
        if v is None:
            return (1, "")
        if isinstance(v, (int, float)):
            return (0, v)
        if isinstance(v, (date, datetime)):
            return (0, v.isoformat())
        return (0, str(v).casefold())
    present = [r for r in rows if r.get(key) is not None]
    missing = [r for r in rows if r.get(key) is None]
    return sorted(present, key=k, reverse=desc) + missing


def base_context(request: Request, db: Session | None) -> dict:
    user = getattr(request.state, "user", None)
    sess = getattr(request.state, "auth", None)
    msg = None
    raw = request.cookies.get(FLASH)
    if raw:
        try:
            msg = _signer().loads(raw)
            # the undo URL must be one of our own paths (the cookie is signed, this is belt and braces)
            if len(msg) > 2 and not (isinstance(msg[2], str) and msg[2].startswith("/") and not msg[2].startswith("//")):
                msg = msg[:2]
        except BadSignature:
            msg = None
    ctx = {"request": request, "user": user, "csrf": sess.csrf_token if sess else "", "nav": NAV,
           "can": (lambda p: security.has_permission(user, p)), "flash_msg": msg, "fmt": fmt, "pill": pill, "cell": cell,
           "query": lambda **kw: query(request, **kw), "version": __version__, "settings": get_settings(),
           "today": date.today(), "humanize": humanize, "static_v": STATIC_V, "erp_ready": erp_ready(request) if user else False}
    if db is not None and user is not None:
        ctx["sync_state"] = sync.staleness(db, sync.latest_snapshot(db))
        ctx["dq_open"] = sum(dq.open_counts(db).values())
    return ctx


def render(request: Request, db: Session | None, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    full = base_context(request, db)
    full.update(ctx)
    resp = templates.TemplateResponse(request, name, full, status_code=status_code)
    if request.cookies.get(FLASH):
        resp.delete_cookie(FLASH)
    return resp


def chart_json(data) -> str:
    def default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        raise TypeError
    return json.dumps(data, default=default).replace("</", "<\\/")


def report_page(request: Request, db: Session, key: str, active: str, kicker: str, title: str | None = None,
                extra: dict | None = None, template: str = "report_view.html", per_page: int = 50, hide=()):
    """Render a Reports-Center definition as an interactive page (filters, sort, paging, export)."""
    from ..services import reports
    rdef = reports.REGISTRY[key]
    params = {f.name: request.query_params.get(f.name) for f in rdef.filters if request.query_params.get(f.name)}
    res = reports.run(db, key, params)
    rows = sort_rows(res.rows, request, res.columns)
    pg = paginate(rows, request, per_page)
    filters = [(f, f.options(db) if f.options else None) for f in rdef.filters if f.name not in hide]
    export_q = urlencode(params)
    return render(request, db, template, active=active, kicker=kicker, title=title or rdef.title, res=res, rdef=rdef,
                  pg=pg, filters=filters, params=params, export_q=export_q, **(extra or {}))


class NeedErpPassword(Exception):
    """Live mode, and this session holds no ERP credentials (e.g. after a server restart)."""


def erp_ready(request: Request) -> bool:
    """Can this session talk to Odoo without asking for the ERP password?"""
    from ..odoo import vault
    s = get_settings()
    if not s.is_live or s.sync_configured:
        return True
    sess = getattr(request.state, "auth", None)
    return bool(sess and vault.get(sess.id))


def erp_gateway(request: Request, user, password: str | None = None):
    """Odoo gateway acting as the logged-in user's ERP account (live) or the demo fixture (fake).

    No API key or service account: the user's own ERP login is used, with their Odoo access rights.
    If the in-memory credentials are gone, ``password`` (asked on screen) is verified with Odoo first.
    """
    from ..odoo import vault
    from ..odoo.client import gateway_from_settings
    from ..services import auth
    s = get_settings()
    if not s.is_live:
        return gateway_from_settings()
    sess = request.state.auth
    creds = vault.get(sess.id)
    if creds is None and password:
        key = (user.login.lower(), "erp-reauth")
        if auth.throttle.blocked(key):
            raise auth.AuthError("Too many wrong ERP passwords. Try again in 15 minutes.")
        uid = gateway_from_settings().authenticate(user.login, password)
        if not uid or (user.odoo_uid and uid != user.odoo_uid):
            auth.throttle.fail(key)
            raise auth.AuthError("ERP password is incorrect.")
        auth.throttle.reset(key)
        vault.put(sess.id, uid, user.login, password, s.session_hours * 3600)
        creds = vault.get(sess.id)
    if creds is None:
        if s.sync_configured:
            return gateway_from_settings()  # optional unattended account
        raise NeedErpPassword()
    return gateway_from_settings(as_user=(creds.uid, creds.secret))


def form_params(request: Request, names) -> dict:
    return {n: request.query_params.get(n) for n in names if request.query_params.get(n) not in (None, "")}
