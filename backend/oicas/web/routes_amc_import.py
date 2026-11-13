"""AMC Import: upload the AMC / ABC Analysis workbook, list the upload sessions, view a session's sheets in a
large modal (Excel-like grid), download the original file, delete a session."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from markupsafe import escape
from sqlalchemy.orm import Session

from ..models import User
from ..services import amc_import
from ..services.exports import fmt
from .common import redirect, render, templates
from .deps import check_csrf, client_ip, get_db, require

router = APIRouter()
ROOT = "/amc-import"


@router.get(ROOT, response_class=HTMLResponse)
def amc_import_home(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return render(request, db, "amc_import.html", active="amc_import", kicker="Analysis", title="AMC Import",
                  imports=amc_import.listing(db), max_mb=amc_import.MAX_BYTES // (1024 * 1024))


@router.post(f"{ROOT}/upload", dependencies=[Depends(check_csrf)])
def amc_import_upload(request: Request, file: UploadFile = File(...), uploaded_by: str = Form(""),
                      db: Session = Depends(get_db), user: User = Depends(require("import.run"))):
    # plain def: FastAPI runs it in a worker thread, so parsing a large workbook does not block other requests
    data = file.file.read(amc_import.MAX_BYTES + 1)
    try:
        imp = amc_import.create(db, user, data, file.filename or "upload.xlsx", uploaded_by, client_ip(request))
    except amc_import.AmcImportError as e:
        db.rollback()
        return redirect(ROOT, str(e), "danger")
    db.commit()
    return redirect(f"{ROOT}?open={imp.id}", f"Session #{imp.id} uploaded: {imp.filename} · {imp.sheet_count} sheets.")


@router.get(f"{ROOT}/{{iid}}/view", response_class=HTMLResponse)
def amc_import_view(iid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    """Modal content: session header and sheet tabs (the first sheet's grid is fetched next)."""
    try:
        imp = amc_import.get(db, iid)
    except amc_import.AmcImportError as e:
        return HTMLResponse(f'<div class="amc-error">{escape(str(e))}</div>', status_code=404)
    return templates.TemplateResponse(request, "amc_import_view.html", {"request": request, "imp": imp, "fmt": fmt})


@router.get(f"{ROOT}/{{iid}}/sheets/{{pos}}", response_class=HTMLResponse)
def amc_import_sheet(iid: int, pos: int, request: Request, page: int = 1, q: str = "", hidden: int = 0,
                     db: Session = Depends(get_db),
                     user: User = Depends(require("view"))):
    """One page of one sheet as an Excel-like grid (fragment)."""
    try:
        s = amc_import.sheet(db, iid, pos)
    except amc_import.AmcImportError as e:
        return HTMLResponse(f'<div class="amc-error">{escape(str(e))}</div>', status_code=404)
    pg = amc_import.page(s, page, q, show_hidden=bool(hidden))
    return templates.TemplateResponse(request, "amc_import_sheet.html",
                                      {"request": request, "s": s, "pg": pg, "iid": iid})


@router.get(f"{ROOT}/{{iid}}/download")
def amc_import_download(iid: int, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(require("view"))):
    try:
        imp = amc_import.get(db, iid)
    except amc_import.AmcImportError:
        return Response("not found", status_code=404)
    amc_import.record_download(db, user, imp, client_ip(request))
    db.commit()
    ascii_name = imp.filename.encode("ascii", "replace").decode().replace('"', "'")
    return Response(imp.content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition":
                             f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(imp.filename)}'})


@router.post(f"{ROOT}/{{iid}}/delete", dependencies=[Depends(check_csrf)])
def amc_import_delete(iid: int, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("import.run"))):
    try:
        imp = amc_import.delete(db, user, iid, client_ip(request))
    except amc_import.AmcImportError as e:
        db.rollback()
        return redirect(ROOT, str(e), "danger")
    db.commit()
    return redirect(ROOT, f"Session #{imp.id} ({imp.filename}) deleted.", "delete")
