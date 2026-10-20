"""Import Center: templates, dry-run validation and all-or-nothing imports."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SyncRun, User
from ..services import importers, imports
from .common import redirect, render
from .deps import check_csrf, get_db, require

router = APIRouter()
MAX_BYTES = 15 * 1024 * 1024
RUNNERS = {"items": imports.import_items, "book_balances": imports.import_book_balances,
           "count_lines": imports.import_count_lines}


@router.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require("import.run"))):
    history = db.scalars(select(SyncRun).where(SyncRun.kind == "import").order_by(SyncRun.id.desc()).limit(30)).all()
    return render(request, db, "imports.html", active="imports", title="Data Import", kicker="Inventory",
                  templates=imports.TEMPLATES, history=history)


@router.get("/imports/template/{kind}.xlsx")
def template(kind: str, user: User = Depends(require("view"))):
    if kind not in imports.TEMPLATES:
        return Response("unknown template", status_code=404)
    return Response(imports.template_workbook(kind),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="OICAS_import_{kind}.xlsx"'})


@router.post("/imports/{kind}", dependencies=[Depends(check_csrf)])
async def run_import(kind: str, request: Request, file: UploadFile = File(...), dry_run: str = Form(""),
                     first_month: str = Form(""), db: Session = Depends(get_db),
                     user: User = Depends(require("import.run"))):
    data = await file.read()
    name = file.filename or f"{kind}.xlsx"
    if len(data) > MAX_BYTES:
        return redirect("/imports", "File too large (max 15 MB).", "danger")
    if kind == "demand":
        if dry_run:
            return redirect("/imports", "Dry run isn't available for demand; it's checked on upload.", "warning")
        from datetime import date
        fm = None
        if first_month:
            y, m = map(int, first_month.split("-")[:2])
            fm = date(y, m, 1)
        try:
            b = importers.upload_demand(db, user, io.BytesIO(data), name, fm)
        except Exception as e:
            db.rollback()
            return redirect("/imports", f"Demand import failed: {e}", "danger")
        db.commit()
        return redirect("/imports", f"Demand batch #{b.id} imported ({b.line_count} item-months, "
                                    f"{b.period_start:%b %Y} – {b.period_end:%b %Y}). Calculate a new analysis on "
                                    "AMC Analysis to use it.")
    if kind not in RUNNERS:
        return redirect("/imports", "Unknown import type.", "danger")
    res = RUNNERS[kind](db, user, io.BytesIO(data), name, dry_run=bool(dry_run))
    if res.ok and not res.dry_run:
        db.commit()
    else:
        db.rollback()  # dry run or errors: nothing is saved
    return render(request, db, "import_result.html", active="imports", title="Import result", kicker="Data Import",
                  res=res, filename=name, tpl=imports.TEMPLATES[kind])


@router.post("/items/{code:path}/rekey", dependencies=[Depends(check_csrf)])
def item_rekey(code: str, new_code: str = Form(...), db: Session = Depends(get_db),
               user: User = Depends(require("item.edit"))):
    try:
        it = imports.rekey_item(db, user, code, new_code)
    except (LookupError, ValueError) as e:
        db.rollback()
        return redirect(f"/items/{code}", str(e), "danger")
    db.commit()
    return redirect(f"/items/{it.code}", f"Item code changed from {code} to {it.code}; all history moved. "
                                         "The next Odoo sync links it to the Odoo product with that code.")
