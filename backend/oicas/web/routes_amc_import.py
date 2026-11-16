"""Workbook upload modules: upload a workbook, list the upload sessions, view a session's sheets in a large modal
(exactly as Excel draws them), download the original file, delete a session.

Two modules share this code, each with its own page, permissions and uploads:
- AMC Import (``/amc-import``): the AMC / ABC Analysis workbook.
- Physical Counting (``/counting``): the COUNTED LIST workbook.
"""
from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class Module:
    kind: str           # amc_import.KINDS key
    root: str           # URL prefix
    active: str         # sidebar entry
    kicker: str
    title: str
    view_perm: str      # see the list, open details, export
    upload_perm: str    # upload
    delete_perm: str    # delete an upload
    upload_title: str
    example: str        # file name shown as an example on the upload form
    help_topic: str


AMC = Module("amc", "/amc-import", "amc_import", "Analysis", "AMC Import", "view", "import.run",
             "import.run", "Upload the AMC / ABC Analysis workbook", "03_AMC Sep-Jul ABC Analysis.xlsx", "amc_import")
COUNTING = Module("counted", "/counting", "counting", "Inventory", "Physical Counting", "count.enter", "count.enter",
                  "count.finalize", "Upload the COUNTED LIST workbook", "COUNTED LIST.xlsx", "counting")


def _error(e: Exception) -> HTMLResponse:
    return HTMLResponse(f'<div class="amc-error">{escape(str(e))}</div>', status_code=404)


def mount(m: Module) -> None:
    """Register the page, upload, viewer, download and delete routes of one module."""

    def home(request: Request, db: Session = Depends(get_db), user: User = Depends(require(m.view_perm))):
        return render(request, db, "amc_import.html", active=m.active, kicker=m.kicker, title=m.title, mod=m,
                      imports=amc_import.listing(db, m.kind), max_mb=amc_import.MAX_BYTES // (1024 * 1024))

    def upload(request: Request, file: UploadFile = File(...), uploaded_by: str = Form(""),
               db: Session = Depends(get_db), user: User = Depends(require(m.upload_perm))):
        # plain def: FastAPI runs it in a worker thread, so parsing a large workbook does not block other requests
        data = file.file.read(amc_import.MAX_BYTES + 1)
        try:
            imp = amc_import.create(db, user, data, file.filename or "upload.xlsx", uploaded_by, client_ip(request),
                                    kind=m.kind)
        except amc_import.AmcImportError as e:
            db.rollback()
            return redirect(m.root, str(e), "danger")
        db.commit()
        return redirect(f"{m.root}?open={imp.id}",
                        f"Session #{imp.number} uploaded: {imp.filename} · {imp.sheet_count} sheets.")

    def view(iid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require(m.view_perm))):
        """Modal content: session header and sheet tabs (the first sheet's grid is fetched next)."""
        try:
            imp = amc_import.get(db, iid, m.kind)
        except amc_import.AmcImportError as e:
            return _error(e)
        return templates.TemplateResponse(request, "amc_import_view.html",
                                          {"request": request, "imp": imp, "fmt": fmt, "mod": m})

    def sheet(iid: int, pos: int, request: Request, page: int = 1, q: str = "", hidden: int = 0,
              db: Session = Depends(get_db), user: User = Depends(require(m.view_perm))):
        """One page of one sheet as an Excel-like grid (fragment)."""
        try:
            s = amc_import.sheet(db, iid, pos, m.kind)
        except amc_import.AmcImportError as e:
            return _error(e)
        pg = amc_import.page(s, page, q, show_hidden=bool(hidden))
        return templates.TemplateResponse(request, "amc_import_sheet.html",
                                          {"request": request, "s": s, "pg": pg, "iid": iid})

    def download(iid: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require(m.view_perm))):
        try:
            imp = amc_import.get(db, iid, m.kind)
        except amc_import.AmcImportError:
            return Response("not found", status_code=404)
        amc_import.record_download(db, user, imp, client_ip(request))
        db.commit()
        ascii_name = imp.filename.encode("ascii", "replace").decode().replace('"', "'")
        return Response(imp.content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(imp.filename)}'})

    def delete(iid: int, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require(m.delete_perm))):
        try:
            imp = amc_import.delete(db, user, iid, client_ip(request), kind=m.kind)
        except amc_import.AmcImportError as e:
            db.rollback()
            return redirect(m.root, str(e), "danger")
        db.commit()
        return redirect(m.root, f"Session #{imp.number} ({imp.filename}) deleted.", "delete")

    name = m.active
    router.add_api_route(m.root, home, methods=["GET"], response_class=HTMLResponse, name=f"{name}_home")
    router.add_api_route(f"{m.root}/upload", upload, methods=["POST"], dependencies=[Depends(check_csrf)],
                         name=f"{name}_upload")
    router.add_api_route(f"{m.root}/{{iid}}/view", view, methods=["GET"], response_class=HTMLResponse,
                         name=f"{name}_view")
    router.add_api_route(f"{m.root}/{{iid}}/sheets/{{pos}}", sheet, methods=["GET"], response_class=HTMLResponse,
                         name=f"{name}_sheet")
    router.add_api_route(f"{m.root}/{{iid}}/download", download, methods=["GET"], name=f"{name}_download")
    router.add_api_route(f"{m.root}/{{iid}}/delete", delete, methods=["POST"], dependencies=[Depends(check_csrf)],
                         name=f"{name}_delete")


mount(AMC)
mount(COUNTING)
