"""Annual Inventory: a log of item code / quantity / location / remarks per plant (P1-P4), area and section.

The landing page lists the plants; hovering a plant opens Warehouse / Production and their sections, which lead
straight to the log page /annual-inventory/P1/warehouse/1. The breadcrumb always shows where you are.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from ..models import User
from ..services import annual, annual_export
from .common import redirect, render
from .deps import check_csrf, client_ip, get_db, require

router = APIRouter()
ROOT = "/annual-inventory"


def _url(period: str | None = None, area: str | None = None, section: int | None = None) -> str:
    parts = [ROOT]
    if period:
        parts.append(period)
        if area:
            parts.append(area.lower())
            if section:
                parts.append(str(section))
    return "/".join(parts)


def _crumbs(period: str | None, area: str | None, section: int | None) -> list[tuple[str, str | None]]:
    """Breadcrumb parts. Plant and area have no page of their own (pick them on the landing page), so they don't link."""
    c: list[tuple[str, str | None]] = [("Annual Inventory", _url())]
    if period:
        c.append((annual.PERIOD_LABELS[period], None))
    if area:
        c.append((annual.AREAS[area], None))
    if section:
        c.append((f"Section {section}", _url(period, area, section)))
    return c


def _back(period: str, area: str, section: str) -> str:
    """Where a form post returns to: the log page it came from (or the landing page)."""
    return _url(*annual.parse_scope(period, area, section))


def _page(request: Request, db: Session, period=None, area=None, section=None, **ctx):
    crumbs = _crumbs(period, area, section)
    return render(request, db, "annual_inventory.html", active="annual", title="Annual Inventory", kicker="Inventory",
                  period=period, area=area, section=section, crumbs=crumbs, back=_url() if len(crumbs) > 1 else None,
                  url=_url, summ=annual.summary(db), rollup=annual.rollup, periods=annual.PERIODS,
                  period_labels=annual.PERIOD_LABELS, areas=annual.AREAS, sections=annual.SECTIONS, **ctx)


@router.get("/annual-inventory", response_class=HTMLResponse)
def choose_plant(request: Request, db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    return _page(request, db, step="plant")


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download(data: bytes, name: str) -> Response:
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/annual-inventory/export.xlsx")  # declared before /{period} so it is not read as a plant
def export_all(request: Request, db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    data, name = annual_export.export(db, user, annual_export.all_scopes(), "all", client_ip(request))
    db.commit()
    return _download(data, name)


@router.get("/annual-inventory/{period}/{area}/{section}/export.xlsx")
def export_section(period: str, area: str, section: str, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require("count.enter"))):
    p, a, s = annual.parse_scope(period, area, section)
    if s is None:
        return Response("not found", status_code=404)
    data, name = annual_export.export(db, user, [(p, a, s)], f"{p}_{a.lower()}_s{s}", client_ip(request))
    db.commit()
    return _download(data, name)


@router.get("/annual-inventory/{period}", response_class=HTMLResponse)
@router.get("/annual-inventory/{period}/{area}", response_class=HTMLResponse)
def old_step(period: str, area: str = "", user: User = Depends(require("count.enter"))):
    """Plant and area have no page of their own: choose them from the landing page."""
    return redirect(ROOT)


@router.get("/annual-inventory/{period}/{area}/{section}", response_class=HTMLResponse)
def log_page(period: str, area: str, section: str, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require("count.enter"))):
    p, a, s = annual.parse_scope(period, area, section)
    if s is None:
        return redirect(ROOT)
    rows = annual.entries(db, p, a, s)
    return _page(request, db, p, a, s, step="log", rows=rows, recon=annual.reconcile(rows), limit=annual.MAX_ROWS,
                 next_no=annual.next_entry_no(db, p, a, s), start_no=annual.START_NO)


@router.post("/annual-inventory/entries", dependencies=[Depends(check_csrf)])
def annual_add(request: Request, period: str = Form(""), area: str = Form(""), section: str = Form(""),
               item_code: str = Form(""), qty: str = Form(""), location: str = Form(""), remarks: str = Form(""),
               entry_no: str = Form(""), db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    back = _back(period, area, section)
    try:
        e = annual.add(db, user, period, area, section, item_code, qty, location, remarks, client_ip(request),
                       entry_no=entry_no)
    except annual.AnnualError as ex:
        db.rollback()
        return redirect(back, str(ex), "danger")
    db.commit()
    return redirect(back, f"Logged No. {e.entry_no} · {e.item_code} · {e.qty:g} · {e.location}.")


@router.post("/annual-inventory/entries/{eid}/edit", dependencies=[Depends(check_csrf)])
def annual_edit(eid: int, request: Request, period: str = Form(""), area: str = Form(""), section: str = Form(""),
                item_code: str = Form(""), qty: str = Form(""), location: str = Form(""), remarks: str = Form(""),
                entry_no: str = Form(""), db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    back = _back(period, area, section)
    try:
        e = annual.update(db, user, eid, item_code, qty, location, remarks, client_ip(request), entry_no=entry_no)
    except annual.AnnualError as ex:
        db.rollback()
        return redirect(back, str(ex), "danger")
    db.commit()
    return redirect(back, f"Updated No. {e.entry_no} · {e.item_code} · {e.qty:g} · {e.location}.", "info")


@router.post("/annual-inventory/entries/{eid}/delete", dependencies=[Depends(check_csrf)])
def annual_delete(eid: int, request: Request, period: str = Form(""), area: str = Form(""), section: str = Form(""),
                  db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    back = _back(period, area, section)
    try:
        e, row = annual.delete(db, user, eid, client_ip(request))
    except annual.AnnualError as ex:
        db.rollback()
        return redirect(back, str(ex), "danger")
    db.commit()
    return redirect(back, f"Deleted No. {e.entry_no} · {e.item_code} · {e.qty:g} · {e.location}.", "delete",
                    undo=f"{ROOT}/undo/{row.id}")


@router.post("/annual-inventory/undo/{audit_id}", dependencies=[Depends(check_csrf)])
def annual_undo(audit_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("count.enter"))):
    try:
        e = annual.restore(db, user, audit_id, client_ip(request))
    except annual.AnnualError as ex:
        db.rollback()
        return redirect(ROOT, str(ex), "danger")
    db.commit()
    return redirect(_url(e.period, e.area, e.section), f"Restored No. {e.entry_no} · {e.item_code} · {e.qty:g} · {e.location}.")


@router.get("/api/annual-inventory/lookup")
def annual_lookup(q: str = "", db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    return annual.lookup(db, q)


@router.get("/api/annual-inventory/suggest")
def annual_suggest(field: str = "item_code", q: str = "", db: Session = Depends(get_db),
                   user: User = Depends(require("count.enter"))):
    return annual.suggest(db, field, q)
