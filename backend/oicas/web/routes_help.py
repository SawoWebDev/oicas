"""Help Center (/help) and context help panel (F1 / ? button on every page)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..models import User
from .common import base_context, render, templates
from .deps import get_db, require

router = APIRouter()

# (key, title, icon, group). Keys of module topics match the sidebar "active" keys, so F1 opens
# the help of the page you are on.
TOPICS: list[tuple[str, str, str, str]] = [
    ("overview", "What is OICAS?", "bi-info-circle", "Start here"),
    ("getting-started", "Getting started", "bi-rocket-takeoff", "Start here"),
    ("workflow", "The complete workflow", "bi-diagram-3", "Start here"),
    ("relationships", "How the data is connected", "bi-share", "Start here"),
    ("dashboard", "Dashboard", "bi-grid", "Modules"),
    ("masterlist", "Inventory Masterlist & item page", "bi-list-ul", "Modules"),
    ("planning", "Cycle Count Planning", "bi-calendar2-check", "Modules"),
    ("counting", "Physical Counting", "bi-clipboard-check", "Modules"),
    ("history", "Count History", "bi-clock-history", "Modules"),
    ("reconciliation", "Odoo Reconciliation & discrepancy review", "bi-arrow-left-right", "Modules"),
    ("imports", "Data Import (data not in Odoo)", "bi-upload", "Modules"),
    ("amc", "AMC Analysis & analysis runs", "bi-graph-up", "Modules"),
    ("abc", "ABC Analysis", "bi-bar-chart-steps", "Modules"),
    ("movement", "Movement Classification", "bi-speedometer2", "Modules"),
    ("reports", "Reports Center & exports", "bi-file-earmark-bar-graph", "Modules"),
    ("dq", "Data Quality", "bi-exclamation-diamond", "Modules"),
    ("sync", "Loading from Odoo (Synchronization)", "bi-arrow-repeat", "Modules"),
    ("audit", "Audit Trail", "bi-shield-check", "Modules"),
    ("config", "System Configuration", "bi-gear", "Modules"),
    ("formulas", "Formulas & KPI definitions", "bi-calculator", "Reference"),
    ("roles", "Roles & permissions", "bi-people", "Reference"),
    ("glossary", "Glossary", "bi-book", "Reference"),
    ("faq", "FAQ & troubleshooting", "bi-question-circle", "Reference"),
    ("shortcuts", "Keyboard shortcuts", "bi-keyboard", "Reference"),
]
TOPIC_KEYS = {k for k, *_ in TOPICS}
PUBLIC_TOPICS = {"login"}  # readable before signing in
RELATED = {
    "dashboard": ["formulas", "masterlist", "reports"],
    "masterlist": ["planning", "reconciliation", "relationships"],
    "planning": ["counting", "formulas", "masterlist"],
    "counting": ["reconciliation", "planning", "imports"],
    "history": ["counting", "reconciliation"],
    "reconciliation": ["counting", "sync", "imports"],
    "imports": ["sync", "relationships", "counting"],
    "amc": ["abc", "movement", "imports"],
    "abc": ["amc", "movement", "formulas"],
    "movement": ["abc", "planning"],
    "reports": ["formulas", "dashboard"],
    "dq": ["sync", "imports"],
    "sync": ["config", "reconciliation", "imports"],
    "audit": ["roles"],
    "config": ["sync", "roles", "formulas"],
    "login": ["getting-started", "roles"],
}
TITLES = {k: t for k, t, *_ in TOPICS} | {"login": "Signing in"}


def _topic(key: str) -> str:
    return key if key in TOPIC_KEYS or key in PUBLIC_TOPICS else "overview"


@router.get("/help", response_class=HTMLResponse)
def help_center(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    groups: dict[str, list] = {}
    for k, t, icon, g in TOPICS:
        groups.setdefault(g, []).append((k, t, icon))
    return render(request, db, "help/center.html", active="help", title="Help Center", kicker="Help",
                  topics=TOPICS, groups=groups)


def _panel(request: Request, key: str, public: bool):
    ctx = base_context(request, None)
    ctx.update(key=key, title=TITLES.get(key, key), related=RELATED.get(key, []), titles=TITLES, public=public)
    return templates.TemplateResponse(request, "help/panel.html", ctx)


@router.get("/help/topic/login", response_class=HTMLResponse)
def help_login_topic(request: Request):
    return _panel(request, "login", True)


@router.get("/help/topic/{key}", response_class=HTMLResponse)
def help_topic(key: str, request: Request, user: User = Depends(require("view"))):
    return _panel(request, _topic(key), False)
