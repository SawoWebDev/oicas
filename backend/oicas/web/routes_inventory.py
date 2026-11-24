"""Masterlist, item detail, planning, counting, count history, reconciliation."""
from __future__ import annotations

import io
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..engine import scheduling
from ..engine.classification import action_priority
from ..engine.reconciliation import BUCKETS
from ..models import (CountEntry, CountPlan, CountPlanItem, CountSession, DiscrepancyNote, DqException, Item,
                      Reconciliation, User)
from ..security import has_permission
from ..services import counting, cyclecount, importers, inventory, masterlist as masterlist_svc, rules, sync
from .common import cell, redirect, render, report_page
from .deps import check_csrf, get_db, require

router = APIRouter()


def _d(v: str | None) -> date | None:
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


# ------------------------------------------------------------------ masterlist & items
@router.get("/masterlist", response_class=HTMLResponse)
def masterlist(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    extra = {"cell": _remark_cell} if has_permission(user, "item.edit") else None
    return report_page(request, db, "masterlist", "masterlist", "Inventory", "Inventory Masterlist", extra=extra)


def _remark_box(code: str, remark: str | None, saved: bool = False) -> str:
    from markupsafe import Markup, escape
    mark = '<i class="bi bi-check2 text-success ms-1" title="Saved"></i>' if saved else ""
    return Markup(f'<form class="ml-remark d-flex align-items-center" hx-post="/masterlist/remark" hx-trigger="change" '
                  f'hx-swap="outerHTML"><input type="hidden" name="code" value="{escape(code)}">'
                  f'<input class="form-control form-control-sm" name="remark" maxlength="1000" '
                  f'value="{escape(remark or "")}" placeholder="Add remark" aria-label="Remark for {escape(code)}">'
                  f'{mark}</form>')


def _remark_cell(row: dict, col) -> str:
    """Masterlist cells; Remarks is an edit box (saved on change) for users who may edit items."""
    if col.key == "remark":
        return _remark_box(row["code"], row.get("remark"))
    return cell(row, col)


@router.post("/masterlist/remark", response_class=HTMLResponse, dependencies=[Depends(check_csrf)])
def masterlist_remark(code: str = Form(...), remark: str = Form(""), db: Session = Depends(get_db),
                      user: User = Depends(require("item.edit"))):
    try:
        value = masterlist_svc.set_remark(db, user, code, remark)
    except ValueError as e:
        db.rollback()
        return HTMLResponse(str(e), status_code=400)
    db.commit()
    return HTMLResponse(_remark_box(code, value, saved=True))


@router.get("/items/{code:path}", response_class=HTMLResponse)
def item_detail(code: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    it = db.scalars(select(Item).where(Item.code == code)).first()
    if it is None:
        return render(request, db, "404.html", status_code=404, what=f"Item {code}")
    row = next((r for r in inventory.build(db, include_untracked=True).rows if r.code == code), None)
    hist = counting.history(db, code)
    from ..services import analysis
    run = analysis.current_run(db)
    results = []
    if run:
        from ..models import AnalysisResult
        results = db.scalars(select(AnalysisResult).where(AnalysisResult.run_id == run.id,
                                                          AnalysisResult.item_code == code)).all()
    issues = db.scalars(select(DqException).where(DqException.status == "open",
                                                  (DqException.ref == code) | DqException.ref.like(f"%/{code}")
                                                  | DqException.ref.like(f"{code}/%"))).all()
    months = []
    if run:
        from ..engine.amc import Period
        months = Period(run.period_start, run.months).months
    return render(request, db, "item_detail.html", active="masterlist", item=it, row=row, hist=hist, results=results,
                  run=run, months=months, issues=issues,
                  options={"material_sections": rules.get_setting(db, "material_sections"),
                           "abc_families": rules.get_setting(db, "abc_families"),
                           "plant_locations": rules.get_setting(db, "plant_locations")})


@router.post("/items/{code:path}", dependencies=[Depends(check_csrf)])
def item_update(code: str, request: Request, material_section: str = Form(""), abc_family: str = Form(""),
                plant_location: str = Form(""), remark: str = Form(""), is_jit: str = Form(""), tracked: str = Form(""),
                db: Session = Depends(get_db), user: User = Depends(require("item.edit"))):
    try:
        inventory.update_item(db, user, code, {"material_section": material_section, "abc_family": abc_family,
                                               "plant_location": plant_location, "remark": remark,
                                               "is_jit": bool(is_jit), "tracked": bool(tracked)})
    except (LookupError, ValueError) as e:
        db.rollback()
        return redirect(f"/items/{code}", str(e), "danger")
    db.commit()
    return redirect(f"/items/{code}", "Item attributes saved.")


# ------------------------------------------------------------------ planning
@router.get("/planning", response_class=HTMLResponse)
def planning(request: Request, view: str = "calendar", month: str = "", q: str = "", db: Session = Depends(get_db),
             user: User = Depends(require("view"))):
    """Cycle Count Planning. Each month is its own saved copy of the Inventory Masterlist (see Import)."""
    view = "list" if view == "list" else "calendar"
    today = date.today()
    y, m = cyclecount.parse_month(month, today)
    key = cyclecount.month_key(y, m)
    items = cyclecount.entries(db, key)
    ctx = {"view": view, "y": y, "m": m, "q": q.strip(), "total": len(items), "month_start": date(y, m, 1),
           "month_key": key, "today_month": today.strftime("%Y-%m"),
           "prev_month": cyclecount.month_key(*cyclecount.shift(y, m, -1)),
           "next_month": cyclecount.month_key(*cyclecount.shift(y, m, 1)),
           "imported_at": cyclecount.last_import(db, key)}
    if view == "calendar":
        by_day: dict[date, list] = {}
        for e in items:
            by_day.setdefault(e.date, []).append(e)
        ctx.update(weeks=cyclecount.month_weeks(y, m), by_day=by_day,
                   month_count=sum(1 for e in items if (e.date.year, e.date.month) == (y, m)))
    else:
        ctx.update(rows=_planning_rows(items, q))
    return render(request, db, "planning.html", active="planning", kicker="Inventory", title="Cycle Count Planning", **ctx)


def _planning_rows(items, q: str):
    needle = q.strip().casefold()
    if not needle:
        return items
    return [e for e in items if needle in e.code.casefold() or needle in (e.description or "").casefold()]


@router.post("/planning/import", dependencies=[Depends(check_csrf)])
def planning_import(month: str = Form(...), view: str = Form("calendar"), db: Session = Depends(get_db),
                    user: User = Depends(require("plan.manage"))):
    """Import Inventory Masterlist: copy what the masterlist holds now into this month."""
    y, m = cyclecount.parse_month(month, date.today())
    key = cyclecount.month_key(y, m)
    res = cyclecount.import_masterlist(db, user, key)
    db.commit()
    back = f"/planning?view={'list' if view == 'list' else 'calendar'}&month={key}"
    if not res["total"] and not res["removed"]:
        return redirect(back, "The Inventory Masterlist has no code with a Next Count to import.", "warning")
    return redirect(back, f"Imported the Inventory Masterlist into {date(y, m, 1):%B %Y}: {res['added']} added, "
                          f"{res['updated']} updated, {res['removed']} removed ({res['total']} codes).")


@router.post("/planning/import-schedule", dependencies=[Depends(check_csrf)])
async def planning_import_schedule(month: str = Form(...), view: str = Form("calendar"), file: UploadFile = File(...),
                                   db: Session = Depends(get_db), user: User = Depends(require("plan.manage"))):
    """Import schedule: the SCHEDULE sheet (xlsx or csv) becomes this month's list, CALENDAR column = date."""
    y, m = cyclecount.parse_month(month, date.today())
    key = cyclecount.month_key(y, m)
    back = f"/planning?view={'list' if view == 'list' else 'calendar'}&month={key}"
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        return redirect(back, "File too large (max 25 MB).", "danger")
    try:
        parsed = cyclecount.parse_schedule(data, file.filename or "schedule.csv", date(y, m, 15))
    except Exception as e:  # noqa: BLE001 - malformed upload
        return redirect(back, f"Could not read the schedule: {e}", "danger")
    if not parsed["rows"]:
        return redirect(back, "No rows with a code and a CALENDAR date were found.", "danger")
    res = cyclecount.import_schedule(db, user, key, parsed["rows"])
    db.commit()
    extra = []
    if res["not_in_masterlist"]:
        extra.append(f"{res['not_in_masterlist']} not in the Inventory Masterlist")
    if parsed["duplicates"]:
        extra.append(f"{parsed['duplicates']} repeated code(s) kept on their latest date")
    if parsed["skipped"]:
        extra.append(f"{parsed['skipped']} row(s) without a date skipped")
    msg = (f"Imported the schedule into {date(y, m, 1):%B %Y}: {res['total']} codes ({res['added']} added, "
           f"{res['updated']} updated, {res['removed']} removed)")
    return redirect(back, msg + (f". {'; '.join(extra)}." if extra else "."))


@router.get("/planning/lookup")
def planning_lookup(code: str = "", month: str = "", db: Session = Depends(get_db),
                    user: User = Depends(require("view"))):
    y, m = cyclecount.parse_month(month, date.today())
    e = cyclecount.find(db, cyclecount.month_key(y, m), code)
    if e is None:
        return JSONResponse({"found": False})
    return JSONResponse({"found": True, "code": e.code, "description": e.description or "",
                         "classification": e.classification or "", "plant_location": e.plant_location or "",
                         "original_date": e.original_date.isoformat(),
                         "adjusted_date": e.adjusted_date.isoformat() if e.adjusted_date else "",
                         "in_charge": e.in_charge or ""})


@router.post("/planning/adjust", dependencies=[Depends(check_csrf)])
def planning_adjust(code: str = Form(...), month: str = Form(...), adjusted_date: str = Form(...),
                    db: Session = Depends(get_db), user: User = Depends(require("plan.manage"))):
    """The entry row at the top of the list: set the Adjusted Date of one code in this month."""
    y, m = cyclecount.parse_month(month, date.today())
    key = cyclecount.month_key(y, m)
    try:
        d = _d(adjusted_date)
        if d is None:
            raise ValueError("Adjusted date is required")
        e = cyclecount.set_adjustment(db, user, key, code, adjusted_date=d)
    except ValueError as err:
        db.rollback()
        return redirect(f"/planning?view=list&month={key}", str(err), "danger")
    db.commit()
    return redirect(f"/planning?view=list&month={key}", f"{e.code} scheduled on {e.date.strftime('%b %d, %Y')}.")


@router.post("/planning/save", dependencies=[Depends(check_csrf)])
async def planning_save(request: Request, db: Session = Depends(get_db), user: User = Depends(require("plan.manage"))):
    """Save button under the list: every edited row (code, adjusted_date, in_charge) of the month in one go."""
    form = await request.form()
    y, m = cyclecount.parse_month(form.get("month"), date.today())
    key = cyclecount.month_key(y, m)
    back = form.get("back") or f"/planning?view=list&month={key}"
    if not back.startswith("/planning") or back.startswith("//"):
        back = f"/planning?view=list&month={key}"
    codes, dates, people = form.getlist("code"), form.getlist("adjusted_date"), form.getlist("in_charge")
    if not (len(codes) == len(dates) == len(people)):
        return redirect(back, "The changes could not be read. Reload the page and try again.", "danger")
    try:
        for c, dt, who in zip(codes, dates, people):
            d = _d(dt)
            if dt.strip() and d is None:
                raise ValueError(f"{c}: adjusted date is not a valid date")
            cyclecount.set_adjustment(db, user, key, c, adjusted_date=d, in_charge=who)
    except ValueError as err:
        db.rollback()
        return redirect(back, str(err), "danger")
    db.commit()
    return redirect(back, f"Saved {len(codes)} row(s).")


@router.get("/planning/export.xlsx")
def planning_export(month: str = "", q: str = "", db: Session = Depends(get_db), user: User = Depends(require("view"))):
    from ..services import exports
    from ..services.reports import Column, ReportResult
    y, m = cyclecount.parse_month(month, date.today())
    key = cyclecount.month_key(y, m)
    rows = _planning_rows(cyclecount.entries(db, key), q)
    cols = [Column("original_date", "Original Date", "longdate"), Column("code", "Code"),
            Column("adjusted_date", "Adjusted Date", "longdate"), Column("description", "Description"),
            Column("classification", "Classification"), Column("plant_location", "Plant Location"),
            Column("in_charge", "In Charge"), Column("last_edit", "Last Edited")]
    res = ReportResult("cycle_count_planning", "Cycle Count Planning", cols, [e.as_dict() for e in rows],
                       meta={"filters": {"month": date(y, m, 1).strftime("%B %Y"), **({"q": q} if q else {})}})
    return Response(exports.to_xlsx(res), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="cycle_count_{key}.xlsx"'})


@router.post("/planning/plans", dependencies=[Depends(check_csrf)])
async def plan_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("plan.manage"))):
    form = await request.form()
    codes = form.getlist("codes")
    mode = form.get("mode", "selected")
    ds = inventory.build(db)
    if mode != "selected":
        statuses = {"due": ("overdue", "due_today"), "due_upcoming": ("overdue", "due_today", "upcoming")}[mode]
        rows = [r for r in ds.rows if r.due_status in statuses]
        if form.get("plant_location"):
            rows = [r for r in rows if r.plant_location == form.get("plant_location")]
        codes = [r.code for r in rows]
    by_code = {r.code: r for r in ds.rows}
    items = []
    for c in codes:
        r = by_code.get(c)
        if r is None:
            continue
        reason = "never_counted" if r.last_count_date is None else ("overdue" if r.due_status == "overdue" else "scheduled")
        items.append((c, reason, action_priority(r.action) * 1000 + min(999, 999 - min(r.overdue_days, 999))))
    try:
        assignee = int(form["assignee_id"]) if form.get("assignee_id") else None
        plan = counting.create_plan(db, user, form.get("name", ""), _d(form.get("plan_date")) or date.today(),
                                    _d(form.get("due_date")), items, assignee, form.get("notes") or None)
    except counting.CountError as e:
        db.rollback()
        return redirect("/planning", str(e), "danger")
    db.commit()
    return redirect(f"/planning/plans/{plan.id}", f"Count plan created with {len(plan.items)} items.")


@router.get("/planning/plans/{plan_id}", response_class=HTMLResponse)
def plan_detail(plan_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    plan = db.get(CountPlan, plan_id)
    if plan is None:
        return render(request, db, "404.html", status_code=404, what=f"Plan #{plan_id}")
    rows = {r.code: r for r in inventory.build(db).rows}
    users = db.scalars(select(User).where(User.active.is_(True), User.role != "viewer").order_by(User.name)).all()
    names = {u.id: u.name or u.login for u in users}
    items = sorted(plan.items, key=lambda pi: (pi.priority, pi.item_code))
    sessions = db.scalars(select(CountSession).where(CountSession.plan_id == plan_id).order_by(CountSession.id.desc())).all()
    return render(request, db, "plan_detail.html", active="planning", plan=plan, items=items, rows=rows, users=users,
                  names=names, sessions=sessions)


@router.post("/planning/plans/{plan_id}/assign", dependencies=[Depends(check_csrf)])
async def plan_assign(plan_id: int, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("plan.manage"))):
    form = await request.form()
    ids = [int(i) for i in form.getlist("item_ids")]
    assignee = int(form["assignee_id"]) if form.get("assignee_id") else None
    n = counting.assign_plan_items(db, user, plan_id, ids, assignee)
    db.commit()
    return redirect(f"/planning/plans/{plan_id}", f"{n} item(s) assigned.")


@router.post("/planning/plans/{plan_id}/status", dependencies=[Depends(check_csrf)])
def plan_status(plan_id: int, status: str = Form(...), db: Session = Depends(get_db),
                user: User = Depends(require("plan.manage"))):
    counting.set_plan_status(db, user, plan_id, status)
    db.commit()
    return redirect(f"/planning/plans/{plan_id}", f"Plan {status}.")


@router.get("/planning/plans/{plan_id}/count-sheet.xlsx")
def plan_sheet(plan_id: int, assigned_to_id: int | None = None, db: Session = Depends(get_db),
               user: User = Depends(require("view"))):
    plan = db.get(CountPlan, plan_id)
    rows = {r.code: r for r in inventory.build(db).rows}
    data = []
    for pi in sorted(plan.items, key=lambda pi: (pi.priority, pi.item_code)):
        if assigned_to_id and pi.assigned_to_id != assigned_to_id:
            continue
        r = rows.get(pi.item_code)
        data.append({"code": pi.item_code, "description": r.description if r else "", "uom": r.uom if r else None,
                     "plant_location": r.plant_location if r else None})
    wb = importers.count_sheet_workbook(data, plan.name, plan.id)
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="count_sheet_plan_{plan_id}.xlsx"'})


# ------------------------------------------------------------------ counting
# The Physical Counting page (/counting) lists COUNTED LIST workbook uploads: see routes_amc_import.
# Count sessions created from a plan or a recount keep their own pages below.
@router.post("/counting/sessions", dependencies=[Depends(check_csrf)])
def session_create(count_date: str = Form(...), counted_by: str = Form(...), plan_id: str = Form(""),
                   remarks: str = Form(""), client_token: str = Form(""), recount_of: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    try:
        s = counting.create_session(db, user, _d(count_date) or date.today(), counted_by,
                                    int(plan_id) if plan_id else None, client_token or None, remarks or None,
                                    recount_of=int(recount_of) if recount_of else None)
    except counting.CountError as e:
        db.rollback()
        return redirect("/counting", str(e), "danger")
    db.commit()
    return redirect(f"/counting/sessions/{s.id}", "Count session started.")


@router.post("/counting/count-sheet/upload", dependencies=[Depends(check_csrf)])
async def count_sheet_upload(request: Request, file: UploadFile = File(...), count_date: str = Form(""),
                             counted_by: str = Form(""), plan_id: str = Form(""), client_token: str = Form(""),
                             db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    """A filled count sheet from a plan (Count sheet (Excel) on the plan page) becomes a draft count session."""
    back = f"/planning/plans/{int(plan_id)}" if plan_id.isdigit() else "/planning"
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        return redirect(back, "File too large (max 10 MB).", "danger")
    try:
        s, errors = importers.upload_count_sheet(db, user, io.BytesIO(data), file.filename or "upload.xlsx",
                                                 _d(count_date), counted_by or None, int(plan_id) if plan_id else None,
                                                 client_token or None)
    except Exception as e:  # malformed workbook
        db.rollback()
        return redirect(back, f"Could not read the file: {e}", "danger")
    if errors:
        db.rollback()
        return render(request, db, "counting_upload_errors.html", active="planning", errors=errors,
                      filename=file.filename, back=back)
    db.commit()
    return redirect(f"/counting/sessions/{s.id}", f"Uploaded {len(s.entries)} entries as a draft. Review and submit.")


@router.get("/counting/sessions/{sid}", response_class=HTMLResponse)
def session_detail(sid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    s = db.get(CountSession, sid)
    if s is None:
        return render(request, db, "404.html", status_code=404, what=f"Session #{sid}")
    desc = dict(db.execute(select(Item.code, Item.description).where(
        Item.code.in_({e.item_code for e in s.entries}))).all())
    plan_items = []
    if s.plan_id and s.status == "draft":
        counted = {e.item_code for e in s.entries}
        plan_items = [pi for pi in db.get(CountPlan, s.plan_id).items if pi.item_code not in counted]
    st = sync.staleness(db, sync.latest_snapshot(db))
    recons = db.scalars(select(Reconciliation).where(Reconciliation.count_date == s.count_date,
                                                     Reconciliation.item_code.in_({e.item_code for e in s.entries}),
                                                     Reconciliation.superseded.is_(False))).all() if s.status == "finalized" else []
    return render(request, db, "session_detail.html", active="counting", s=s, desc=desc, plan_items=plan_items[:300],
                  buckets=BUCKETS, slots=rules.get_setting(db, "count_slots"), st=st, recons=recons)


@router.post("/counting/sessions/{sid}/entries", dependencies=[Depends(check_csrf)])
def entry_add(sid: int, request: Request, item_code: str = Form(...), bucket: str = Form(...), qty: str = Form(...),
              slot: str = Form("1"), round_no: int = Form(1), remarks: str = Form(""), db: Session = Depends(get_db),
              user: User = Depends(require("count.enter"))):
    try:
        q = float(qty.replace(",", ""))
        counting.add_entry(db, user, sid, item_code, bucket, q, slot, round_no, remarks or None)
    except ValueError as e:
        db.rollback()
        return redirect(f"/counting/sessions/{sid}", str(e) if isinstance(e, counting.CountError) else
                        "Quantity must be a number.", "danger")
    db.commit()
    return redirect(f"/counting/sessions/{sid}#entry-form", f"Added {item_code}.")


@router.post("/counting/entries/{eid}/remove", dependencies=[Depends(check_csrf)])
def entry_remove(eid: int, db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    e = db.get(CountEntry, eid)
    sid = e.session_id if e else 0
    try:
        counting.remove_draft_entry(db, user, eid)
    except counting.CountError as ex:
        db.rollback()
        return redirect(f"/counting/sessions/{sid}", str(ex), "danger")
    db.commit()
    return redirect(f"/counting/sessions/{sid}", "Entry removed.")


@router.post("/counting/entries/{eid}/correct", dependencies=[Depends(check_csrf)])
def entry_correct(eid: int, qty: str = Form(...), reason: str = Form(""), db: Session = Depends(get_db),
                  user: User = Depends(require("count.finalize"))):
    e = db.get(CountEntry, eid)
    sid = e.session_id if e else 0
    try:
        counting.correct_entry(db, user, eid, float(qty.replace(",", "")), reason)
    except ValueError as ex:
        db.rollback()
        return redirect(f"/counting/sessions/{sid}", str(ex), "danger")
    db.commit()
    return redirect(f"/counting/sessions/{sid}", "Correction recorded; the original entry is kept in history.")


@router.post("/counting/sessions/{sid}/submit", dependencies=[Depends(check_csrf)])
def session_submit(sid: int, db: Session = Depends(get_db), user: User = Depends(require("count.enter"))):
    try:
        counting.submit(db, user, sid)
    except counting.CountError as e:
        db.rollback()
        return redirect(f"/counting/sessions/{sid}", str(e), "danger")
    db.commit()
    return redirect(f"/counting/sessions/{sid}", "Submitted. A manager will finalize it against Odoo.")


@router.post("/counting/sessions/{sid}/finalize", dependencies=[Depends(check_csrf)])
def session_finalize(sid: int, allow_stale: str = Form(""), db: Session = Depends(get_db),
                     user: User = Depends(require("count.finalize"))):
    try:
        counting.finalize(db, user, sid, allow_stale=bool(allow_stale))
    except counting.CountError as e:
        db.rollback()
        return redirect(f"/counting/sessions/{sid}", str(e), "danger")
    db.commit()
    return redirect(f"/counting/sessions/{sid}", "Finalized and reconciled against the Odoo snapshot.")


@router.post("/counting/sessions/{sid}/cancel", dependencies=[Depends(check_csrf)])
def session_cancel(sid: int, reason: str = Form(""), db: Session = Depends(get_db),
                   user: User = Depends(require("count.enter"))):
    try:
        counting.cancel(db, user, sid, reason)
    except counting.CountError as e:
        db.rollback()
        return redirect(f"/counting/sessions/{sid}", str(e), "danger")
    db.commit()
    return redirect(f"/counting/sessions/{sid}", "Session cancelled.")


@router.get("/api/items/search")
def item_search(q: str = "", db: Session = Depends(get_db), user: User = Depends(require("view"))):
    q = q.strip()
    if len(q) < 2:
        return []
    rows = db.execute(select(Item.code, Item.description, Item.uom_name).where(
        (Item.code.ilike(f"%{q}%")) | (Item.description.ilike(f"%{q}%"))).order_by(Item.tracked.desc(), Item.code)
        .limit(20)).all()
    return [{"code": c, "description": d, "uom": u} for c, d, u in rows]


# ------------------------------------------------------------------ count history & reconciliation
@router.get("/history", response_class=HTMLResponse)
def history(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return report_page(request, db, "physical_count", "history", "Inventory", "Count History",
                       {"intro": "Count lines from every COUNTED LIST upload on Physical Counting (pick one upload "
                                 "in the filter to see only that file). Location is the column the quantity is in; UoM comes from "
                                 "Odoo; Remarks come from the COUNTED LIST."})


@router.get("/reconciliation", response_class=HTMLResponse)
def reconciliation(request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return report_page(request, db, "reconciliation", "reconciliation", "Inventory", "Odoo Reconciliation",
                       {"intro": "Physical minus Odoo per location. Open a row to review, request a recount or resolve. "
                                 "OICAS never changes Odoo stock."})


@router.get("/reconciliation/{rid}", response_class=HTMLResponse)
def recon_detail(rid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    r = db.get(Reconciliation, rid)
    if r is None:
        return render(request, db, "404.html", status_code=404, what=f"Reconciliation #{rid}")
    item = db.scalars(select(Item).where(Item.code == r.item_code)).first()
    notes = db.scalars(select(DiscrepancyNote).where(DiscrepancyNote.reconciliation_id == rid)
                       .order_by(DiscrepancyNote.created_at)).all()
    entries = db.execute(select(CountEntry, CountSession).join(CountSession).where(
        CountEntry.item_code == r.item_code, CountSession.count_date == r.count_date)
        .order_by(CountEntry.id)).all()
    users = {u.id: u.name or u.login for u in db.scalars(select(User))}
    from ..models import InventorySnapshot
    snap = db.get(InventorySnapshot, r.snapshot_id) if r.snapshot_id else None
    newer = db.get(Reconciliation, r.superseded_by_id) if r.superseded_by_id else None
    return render(request, db, "recon_detail.html", active="reconciliation", r=r, item=item, notes=notes,
                  entries=entries, users=users, snap=snap, newer=newer,
                  assignees=[u for u in db.scalars(select(User).where(User.active.is_(True), User.role != "viewer"))])


@router.post("/reconciliation/{rid}/review", dependencies=[Depends(check_csrf)])
def recon_review(rid: int, action: str = Form(...), note: str = Form(""), assignee_id: str = Form(""),
                 db: Session = Depends(get_db), user: User = Depends(require("discrepancy.review"))):
    try:
        counting.review(db, user, rid, action, note, int(assignee_id) if assignee_id else None)
    except counting.CountError as e:
        db.rollback()
        return redirect(f"/reconciliation/{rid}", str(e), "danger")
    db.commit()
    msg = {"recount_requested": "Recount requested and added to the 'Recount requests' plan."}.get(action, "Saved.")
    return redirect(f"/reconciliation/{rid}", msg)


__all__ = ["router", "scheduling"]
