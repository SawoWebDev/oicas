"""HTTP-level tests: pages render for each role, permissions and CSRF are enforced server-side,
and the count workflow works end to end through the UI."""
from __future__ import annotations

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from oicas.db import Base, make_engine, session_factory, set_engine
from oicas.models import CountSession, Reconciliation
from oicas.services import rules, sync

from .helpers import fake_odoo, map_locations, track_items


@pytest.fixture(scope="module")
def client():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    set_engine(eng)
    db = session_factory()()
    rules.ensure_default_rule_set(db)
    gw = fake_odoo()
    sync.run_inventory_sync(db, gw)
    map_locations(db)
    sync.run_inventory_sync(db, gw)
    track_items(db)
    db.commit()
    db.close()
    from oicas.web.app import app
    return TestClient(app)


def login(client, who):
    client.cookies.clear()
    r = client.post("/login", data={"login": who, "password": "demo", "method": "odoo"}, follow_redirects=False)
    assert r.status_code == 303, r.text[:500]
    return client


def csrf(client, url="/"):
    html = client.get(url).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


PAGES = ["/", "/masterlist", "/items/A-1", "/planning", "/history", "/reconciliation", "/analysis/amc", "/analysis/abc",
         "/analysis/movement", "/reports", "/data-quality", "/sync"]


def test_login_required(client):
    client.cookies.clear()
    r = client.get("/masterlist", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_bad_login(client):
    client.cookies.clear()
    r = client.post("/login", data={"login": "manager", "password": "nope"})
    assert r.status_code == 401 and "Invalid Odoo login" in r.text


@pytest.mark.parametrize("url", PAGES + ["/counting", "/audit", "/config", "/config?tab=locations", "/config?tab=users",
                                         "/config?tab=settings", "/config?tab=imports"])
def test_admin_pages_render(client, url):
    login(client, "admin")
    r = client.get(url)
    assert r.status_code == 200, r.text[:2000]
    assert "sawo-logo.png" in r.text and "DEMO · secondary DB" in r.text
    assert r.headers["content-security-policy"].startswith("default-src 'self'")


def test_all_report_pages_and_exports(client):
    from oicas.services.reports import REGISTRY
    login(client, "admin")
    for key in REGISTRY:
        assert client.get(f"/reports/{key}").status_code == 200, key
        x = client.get(f"/reports/{key}/export.xlsx")
        assert x.status_code == 200 and x.content[:2] == b"PK", key
    p = client.get("/reports/masterlist/export.pdf?classification=Fast+Moving")
    assert p.status_code == 200 and p.content[:4] == b"%PDF"


def test_viewer_cannot_configure_or_count(client):
    login(client, "viewer")
    assert client.get("/").status_code == 200
    for url in ("/config", "/audit", "/counting"):
        assert client.get(url).status_code == 403, url
    token = csrf(client)
    r = client.post("/sync/run", data={"csrf": token})
    assert r.status_code == 403


def test_csrf_required(client):
    login(client, "manager")
    r = client.post("/sync/run", data={})
    assert r.status_code == 403 and "form token" in r.text


def test_count_workflow_over_http(client):
    login(client, "counter")
    token = csrf(client, "/counting")
    r = client.post("/counting/sessions", data={"csrf": token, "count_date": date.today().isoformat(),
                                                "counted_by": "Christine A", "client_token": "abc123"},
                    follow_redirects=False)
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    r2 = client.post("/counting/sessions", data={"csrf": token, "count_date": date.today().isoformat(),
                                                 "counted_by": "Christine A", "client_token": "abc123"},
                     follow_redirects=False)
    assert r2.headers["location"].endswith(f"/{sid}")  # duplicate submission → same session
    client.post(f"/counting/sessions/{sid}/entries", data={"csrf": token, "item_code": "A-1", "bucket": "WAREHOUSE",
                                                           "qty": "97", "slot": "1"})
    client.post(f"/counting/sessions/{sid}/submit", data={"csrf": token})
    # counters cannot finalize
    assert client.post(f"/counting/sessions/{sid}/finalize", data={"csrf": token}).status_code == 403
    login(client, "manager")
    token = csrf(client, f"/counting/sessions/{sid}")
    r = client.post(f"/counting/sessions/{sid}/finalize", data={"csrf": token})
    assert r.status_code == 200
    db = session_factory()()
    assert db.get(CountSession, sid).status == "finalized"
    rc = db.scalars(select(Reconciliation).where(Reconciliation.item_code == "A-1", Reconciliation.superseded.is_(False))).first()
    assert rc.phys_wh == 97.0 and rc.disc_wh == -3.0
    db.close()
    page = client.get(f"/reconciliation/{rc.id}")
    assert page.status_code == 200 and "-3" in page.text
    r = client.post(f"/reconciliation/{rc.id}/review", data={"csrf": token, "action": "recount_requested", "note": "bin 2"})
    assert r.status_code == 200 and "Recount requested" in r.text


def test_count_sheet_roundtrip(client):
    import io

    from openpyxl import load_workbook
    login(client, "manager")
    token = csrf(client, "/planning")
    r = client.post("/planning/plans", data={"csrf": token, "name": "Test plan", "mode": "selected", "codes": ["A-1", "A-2"]}, follow_redirects=False)
    assert r.status_code == 303 and "/planning/plans/" in r.headers["location"]
    pid = r.headers["location"].rsplit("/", 1)[1]
    x = client.get(f"/planning/plans/{pid}/count-sheet.xlsx")
    wb = load_workbook(io.BytesIO(x.content))
    ws = wb.active
    ws["B2"], ws["B3"] = date.today().isoformat(), "Giniemark"
    ws.cell(7, 5, 12)  # first item, WH-1
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/counting/upload", data={"csrf": token}, files={"file": ("sheet.xlsx", buf.getvalue())},
                    follow_redirects=False)
    assert r.status_code == 303 and "/counting/sessions/" in r.headers["location"], re.findall(r"<li>(.*?)</li>", r.text)


def test_import_center_template_and_dry_run(client):
    import io

    from openpyxl import load_workbook
    login(client, "manager")
    assert client.get("/imports").status_code == 200
    t = client.get("/imports/template/items.xlsx")
    assert t.status_code == 200 and t.content[:2] == b"PK"
    wb = load_workbook(io.BytesIO(t.content))
    wb["DATA"].append(["", "Web gasket", "Piece", "", "", "1", "", "yes"])
    buf = io.BytesIO()
    wb.save(buf)
    token = csrf(client, "/imports")
    r = client.post("/imports/items", data={"csrf": token, "dry_run": "1"}, files={"file": ("i.xlsx", buf.getvalue())})
    assert r.status_code == 200 and "dry run" in r.text and "Would create" in r.text
    r = client.post("/imports/items", data={"csrf": token}, files={"file": ("i.xlsx", buf.getvalue())})
    assert "imported" in r.text
    login(client, "counter")
    assert client.get("/imports").status_code == 403


def test_help_center_and_context_help(client):
    from oicas.web.routes_help import TOPICS
    client.cookies.clear()
    login_page = client.get("/login").text
    assert 'id="help-fab"' in login_page and 'data-help="login"' in login_page
    assert client.get("/help/topic/login").status_code == 200  # readable before signing in
    login(client, "viewer")
    center = client.get("/help")
    assert center.status_code == 200
    for key, *_ in TOPICS:
        assert f'id="help-{key}"' in center.text, key
        r = client.get(f"/help/topic/{key}")
        assert r.status_code == 200 and f'id="help-{key}"' in r.text, key
    # every page carries a help topic that exists (F1 opens the help of the page you're on)
    keys = {k for k, *_ in TOPICS}
    for url in ("/", "/masterlist", "/planning", "/history", "/reconciliation", "/analysis/amc", "/analysis/abc",
                "/analysis/movement", "/reports", "/data-quality", "/sync"):
        topic = re.search(r'data-help="([^"]+)"', client.get(url).text).group(1)
        assert topic in keys, (url, topic)
    assert "F1" in client.get("/static/js/app.js").text


def test_annual_inventory_flow(client):
    from oicas.models import AnnualInventoryEntry, AuditLog
    login(client, "viewer")
    assert client.get("/annual-inventory").status_code == 403
    assert client.get("/api/annual-inventory/suggest?field=location").status_code == 403

    login(client, "counter")
    log_url = "/annual-inventory/P2/warehouse/1"
    # landing: hover a plant → Warehouse / Production → sections; the log page keeps a breadcrumb and a Back link
    plants = client.get("/annual-inventory").text
    assert "Plant 1" in plants and 'id="annual-form"' not in plants and 'class="plant-menu"' in plants
    for target in ("P1/warehouse/1", "P4/production/2"):
        assert f'href="/annual-inventory/{target}"' in plants
    assert 'class="btn btn-soft btn-sm annual-back"' not in plants  # top level: nothing to go back to
    page = client.get(log_url)
    assert page.status_code == 200 and 'id="annual-form"' in page.text and 'aria-current="page">Section 1<' in page.text
    assert 'annual-back" href="/annual-inventory"' in page.text and "Plant 2" in page.text
    assert re.search(r'data-help="annual"', page.text)
    # parts without a page of their own, and unknown parts, go back to the landing page
    for bad_url in ("/annual-inventory/P2", "/annual-inventory/P2/warehouse", "/annual-inventory/P9",
                    "/annual-inventory/P2/attic", "/annual-inventory/P2/warehouse/7"):
        r = client.get(bad_url, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/annual-inventory", bad_url
    token = csrf(client, log_url)
    scope = {"csrf": token, "period": "P2", "area": "WAREHOUSE", "section": "1"}

    def post(url, **kw):
        return client.post(url, data={**scope, **kw}, follow_redirects=False)

    r = post("/annual-inventory/entries", item_code="RM-AN-1", qty="1,250.5", location="Rack A1", remarks="ok")
    assert r.status_code == 303 and r.headers["location"] == log_url
    post("/annual-inventory/entries", item_code="RM-AN-2", qty="3", location="Rack B2")
    # invalid input is refused and nothing is saved (quantity must be a plain number)
    for bad in ({"item_code": "", "qty": "1", "location": "x"}, {"item_code": "X", "qty": "abc", "location": "x"},
                {"item_code": "X", "qty": "-1", "location": "x"}, {"item_code": "X", "qty": "1", "location": " "},
                {"item_code": "X", "qty": "1e5", "location": "x"}, {"item_code": "X", "qty": "nan", "location": "x"},
                {"item_code": "X", "qty": "12abc", "location": "x"}, {"item_code": "X", "qty": "", "location": "x"}):
        post("/annual-inventory/entries", **bad)
    post("/annual-inventory/entries", item_code="X", qty="1", location="x", section="9")  # unknown section: refused

    db = session_factory()()
    rows = db.scalars(select(AnnualInventoryEntry).order_by(AnnualInventoryEntry.id)).all()
    assert [(e.period, e.area, e.section, e.item_code, e.qty, e.location) for e in rows] == [
        ("P2", "WAREHOUSE", 1, "RM-AN-1", 1250.5, "Rack A1"), ("P2", "WAREHOUSE", 1, "RM-AN-2", 3.0, "Rack B2")]
    assert rows[0].created_by_id is not None and rows[0].remarks == "ok"
    first = rows[0].id
    db.close()

    shown = client.get(log_url).text
    assert "RM-AN-1" in shown and "Rack B2" in shown
    assert 'data-who="Demo Counter"' in shown and 'id="detail-modal"' in shown  # who logged it shows in the Details modal
    assert "detail-row" not in shown  # details no longer add a row to the table
    assert "RM-AN-1" not in client.get("/annual-inventory/P1/warehouse/1").text  # other plant
    assert "RM-AN-1" not in client.get("/annual-inventory/P2/production/2").text
    assert "<b>2</b> entries" in client.get("/annual-inventory").text  # counts roll up onto the plant cards

    # suggestions come from the log (prefix matches first, case-insensitive)
    assert client.get("/api/annual-inventory/suggest?field=item_code&q=rm-an").json() == ["RM-AN-1", "RM-AN-2"]
    assert client.get("/api/annual-inventory/suggest?field=location&q=b2").json() == ["Rack B2"]
    assert set(client.get("/api/annual-inventory/suggest?field=location").json()) == {"Rack A1", "Rack B2"}
    assert client.get("/api/annual-inventory/suggest?field=bogus&q=a").json() == []

    r = post(f"/annual-inventory/entries/{first}/edit", item_code="RM-AN-1", qty="10", location="Rack A9", remarks="")
    assert r.status_code == 303
    db = session_factory()()
    e = db.get(AnnualInventoryEntry, first)
    assert (e.qty, e.location, e.remarks) == (10.0, "Rack A9", None) and e.updated_by_id and e.updated_at
    db.close()

    assert "toast-info" in client.get(log_url).text  # the edit's flash message pops up as a blue toast
    r = post(f"/annual-inventory/entries/{first}/delete")
    assert r.status_code == 303
    gone = client.get(log_url).text
    assert 'class="oi-toast toast-delete"' in gone and "alert-dismissible" not in gone  # red toast, no banner row
    undo_url = re.search(r'action="(/annual-inventory/undo/\d+)"', gone).group(1)  # the toast offers Undo
    assert 'data-code="RM-AN-1"' not in gone  # the row is gone from the table
    # Undo brings the entry back (once), keeping who logged it and when
    u = client.post(undo_url, data={"csrf": csrf(client, log_url)}, follow_redirects=False)
    assert u.status_code == 303 and u.headers["location"] == log_url
    back = client.get(log_url).text
    assert "RM-AN-1" in back and "Restored" in back and 'class="oi-toast toast-success"' in back
    db = session_factory()()
    again = db.scalars(select(AnnualInventoryEntry).where(AnnualInventoryEntry.item_code == "RM-AN-1")).one()
    assert again.id != first and again.created_by_id is not None and again.qty == 10.0 and again.location == "Rack A9"
    db.close()
    assert "toast-danger" in client.get(client.post(undo_url, data={"csrf": csrf(client, log_url)}, follow_redirects=False)
                                        .headers["location"]).text  # second undo: already restored
    first = again.id
    assert post(f"/annual-inventory/entries/{first}/delete").status_code == 303  # delete again for the audit check below
    assert post("/annual-inventory/entries/99999/delete").status_code == 303  # unknown id: flash error, no crash
    assert "toast-danger" in client.get(log_url).text
    db = session_factory()()
    assert db.get(AnnualInventoryEntry, first) is None
    actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.action.like("annual.%")).order_by(AuditLog.id))]
    assert actions == ["annual.add", "annual.add", "annual.edit", "annual.delete", "annual.restore", "annual.delete"]
    db.close()
    # CSRF is enforced
    assert client.post("/annual-inventory/entries", data={"item_code": "Z", "qty": "1", "location": "z"}).status_code == 403


def test_annual_entry_numbers(client):
    from oicas.models import AnnualInventoryEntry
    login(client, "counter")
    url = "/annual-inventory/P3/production/2"
    token = csrf(client, url)
    scope = {"csrf": token, "period": "P3", "area": "PRODUCTION", "section": "2"}

    def add(**kw):
        return client.post("/annual-inventory/entries", data={**scope, "item_code": "EN-1", "qty": "1", "location": "L", **kw},
                           follow_redirects=False)

    def nos(sec="2", area="PRODUCTION"):
        db = session_factory()()
        out = db.scalars(select(AnnualInventoryEntry.entry_no).where(
            AnnualInventoryEntry.period == "P3", AnnualInventoryEntry.area == area,
            AnnualInventoryEntry.section == int(sec)).order_by(AnnualInventoryEntry.entry_no)).all()
        db.close()
        return list(out)

    def next_no(u=url):
        return int(re.search(r'id="f-no" name="entry_no" value="(\d+)"', client.get(u).text).group(1))

    assert next_no() == 40900  # first entry of a section
    add()
    assert nos() == [40900] and next_no() == 40901  # the series carries on by itself
    add()
    assert nos() == [40900, 40901] and next_no() == 40902
    # type a number to jump (e.g. after cancellations): the series continues from it
    add(entry_no="40910")
    assert next_no() == 40911
    add()
    assert nos() == [40900, 40901, 40910, 40911] and next_no() == 40912
    # a number can be used once per section; only whole numbers are accepted
    for bad in ("40910", "40x", "0", "-5", "4.5", "1234567890"):
        add(entry_no=bad)
    assert nos() == [40900, 40901, 40910, 40911]
    # another section has its own series
    assert next_no("/annual-inventory/P3/production/1") == 40900
    assert next_no("/annual-inventory/P3/warehouse/2") == 40900
    # editing: change to a free number, but not to one in use; blank keeps the current number
    db = session_factory()()
    eid = db.scalars(select(AnnualInventoryEntry.id).where(AnnualInventoryEntry.period == "P3", AnnualInventoryEntry.entry_no == 40901)).one()
    db.close()
    edit = f"/annual-inventory/entries/{eid}/edit"
    client.post(edit, data={**scope, "item_code": "EN-1", "qty": "1", "location": "L", "entry_no": "40911"})  # taken
    assert 40901 in nos()
    client.post(edit, data={**scope, "item_code": "EN-1", "qty": "2", "location": "L", "entry_no": ""})  # blank: unchanged
    assert 40901 in nos()
    client.post(edit, data={**scope, "item_code": "EN-1", "qty": "2", "location": "L", "entry_no": "40905"})
    assert nos() == [40900, 40905, 40910, 40911]
    # table shows the numbers; deleting the highest frees its number
    page = client.get(url).text
    assert 'class="view entry-no">40911<' in page and "Entry No." in page
    db = session_factory()()
    top = db.scalars(select(AnnualInventoryEntry.id).where(AnnualInventoryEntry.period == "P3", AnnualInventoryEntry.entry_no == 40911)).one()
    db.close()
    client.post(f"/annual-inventory/entries/{top}/delete", data=scope, follow_redirects=False)
    after = client.get(url).text  # carries the Undo toast (one-time message)
    assert int(re.search(r'id="f-no" name="entry_no" value="(\d+)"', after).group(1)) == 40911
    undo = re.search(r'action="(/annual-inventory/undo/\d+)"', after).group(1)
    # Undo puts the number back, unless it has been reused meanwhile
    add(entry_no="40911")  # someone reuses the freed number
    client.post(undo, data={"csrf": token}, follow_redirects=False)
    assert nos() == [40900, 40905, 40910, 40911]  # not restored: only the reused 40911 exists
    refused = client.get(url).text
    assert "toast-danger" in refused and "now used by another entry" in refused


def test_annual_item_code_suggestions(client):
    login(client, "counter")
    token = csrf(client, "/annual-inventory/P4/warehouse/1")
    scope = {"csrf": token, "period": "P4", "area": "WAREHOUSE", "section": "1", "qty": "1", "location": "L"}
    for code in ("ZZ3-1", "3ZZ-2", "Q3Q-3", "QQ-9"):
        client.post("/annual-inventory/entries", data={**scope, "item_code": code}, follow_redirects=False)

    def codes(q):
        return [r["code"] for r in client.get("/api/annual-inventory/lookup", params={"q": q}).json()]

    got = codes("3")  # one character is enough
    assert got and "QQ-9" not in got and {"ZZ3-1", "3ZZ-2", "Q3Q-3"} <= set(got)
    firsts = [i for i, c in enumerate(got) if c.casefold().startswith("3")]
    others = [i for i, c in enumerate(got) if not c.casefold().startswith("3")]
    assert firsts and others and max(firsts) < min(others)  # codes starting with 3 first, then the ones containing it
    assert codes("zz3")[0] == "ZZ3-1"  # case-insensitive
    assert codes("")  # a click on the empty field lists something to pick from


def test_annual_reconciliation_badge_is_a_filter_control(client):
    login(client, "counter")
    url = "/annual-inventory/P4/production/2"
    token = csrf(client, url)
    scope = {"csrf": token, "period": "P4", "area": "PRODUCTION", "section": "2", "location": "L"}
    for code, q in (("RC-1", "10"), ("RC-1", "20"), ("RC-2", "5")):
        client.post("/annual-inventory/entries", data={**scope, "item_code": code, "qty": q}, follow_redirects=False)
    page = client.get(url).text
    assert page.count('data-recon="RC-1"') == 2 and 'data-recon="RC-2"' not in page  # only repeated codes get a badge
    assert 'id="recon-th"' in page and 'data-recon-clear' in page and 'id="recon-chip"' in page
    head = page.split("<thead>")[1].split("</thead>")[0]
    assert head.index("Reconciliation") < head.index("Entry No.") < head.index("Actions")  # Entry No. sits right of Reconciliation
    assert all("text-end" not in th for th in head.split("<th")[:-1])  # data headers are left-aligned; only the last (row menu) isn't
    assert "annual.js" in page and "setRecon" in client.get("/static/js/annual.js").text


def test_annual_excel_export(client):
    import io

    from openpyxl import load_workbook
    from oicas.models import AuditLog
    login(client, "viewer")
    assert client.get("/annual-inventory/export.xlsx").status_code == 403
    login(client, "counter")
    url = "/annual-inventory/P4/warehouse/2"
    token = csrf(client, url)
    scope = {"csrf": token, "period": "P4", "area": "WAREHOUSE", "section": "2", "location": "Rack X"}
    for code, q, no in (("EX-1", "10", ""), ("EX-2", "7.5", ""), ("EX-1", "1,250.5", "40950")):
        client.post("/annual-inventory/entries", data={**scope, "item_code": code, "qty": q, "entry_no": no, "remarks": "r " + code},
                    follow_redirects=False)
    page = client.get(url).text
    assert 'href="/annual-inventory/P4/warehouse/2/export.xlsx"' in page and "Export Excel" in page
    assert 'href="/annual-inventory/export.xlsx"' in client.get("/annual-inventory").text

    r = client.get(url + "/export.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK" and "attachment" in r.headers["content-disposition"]
    assert "annual_inventory_P4_warehouse_s2" in r.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(r.content)).active
    header_row = next(i for i in range(1, 15) if ws.cell(i, 1).value == "Item code")
    heads = [c.value for c in ws[header_row]]
    assert heads[:7] == ["Item code", "Quantity", "Location", "Remarks", "Reconciliation", "Combined qty", "Entry No."]
    data = [[c.value for c in row] for row in ws.iter_rows(min_row=header_row + 1) if row[0].value]
    assert [(d[0], d[1], d[6]) for d in data] == [("EX-1", 10.0, 40900), ("EX-2", 7.5, 40901), ("EX-1", 1250.5, 40950)]  # all rows, by Entry No.
    assert data[0][4] == "First of 2 · total 1,260.5" and data[2][4].startswith("Entry 2 of 2") and data[1][4] in ("", None)
    assert data[0][5] == 1260.5 and data[0][7] == "Demo Counter" and data[0][8] is not None  # logged by / at are in the file
    assert ws.freeze_panes and ws.auto_filter.ref
    # everything: summary sheet + one sheet per section, and bad scopes are 404
    wb = load_workbook(io.BytesIO(client.get("/annual-inventory/export.xlsx").content))
    assert wb.sheetnames[0] == "Summary" and "P4 Warehouse S2" in wb.sheetnames and len(wb.sheetnames) == 1 + 16
    assert client.get("/annual-inventory/P9/warehouse/2/export.xlsx").status_code == 404
    db = session_factory()()
    assert db.scalars(select(AuditLog).where(AuditLog.action == "annual.export")).all()  # exports are audited
    db.close()


def test_logout_revokes_session(client):
    login(client, "admin")
    token = csrf(client)
    client.post("/logout", data={"csrf": token})
    assert client.get("/", follow_redirects=False).status_code == 303


def test_annual_reconcile_groups_same_codes():
    from types import SimpleNamespace as NS
    from oicas.services import annual
    rows = [NS(id=3, item_code="rm-1", qty=5.0), NS(id=1, item_code="RM-1", qty=10.0), NS(id=2, item_code="RM-2", qty=1.0)]
    rec = annual.reconcile(rows)
    assert set(rec) == {1, 3}  # RM-2 was logged once: nothing to reconcile
    assert rec[1] == {"n": 1, "count": 2, "total": 15.0, "first": True}
    assert rec[3]["n"] == 2 and rec[3]["first"] is False


def _amc_workbook() -> bytes:
    import io

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "CONSOLIDATED"
    ws.append(["#", "Code", "Description", "Sep", "demand as a % of total demand", "ACTION", "CLASSIFICATION"])
    ws.append([1, "8RM04-341-1", "Acid - Citric", 745.7, 0.00024064, "CLOSE CONTROL", "Fast Moving"])
    ws.append([2, "8RM05-905", "Acrylic Sheet <b>", 1.67068, 0.5, "REGULAR REVIEW", "Medium Moving"])
    ws["D2"].number_format = "0"
    ws["E2"].number_format = ws["E3"].number_format = "0.00%"
    ws.auto_filter.ref = "A1:G3"
    ws.sheet_properties.tabColor = "00B050"
    cls = wb.create_sheet("CLASS")
    cls["B4"], cls["C4"], cls["D4"] = "DECLARED INVENTORY TYPE", "ACTION", "CLASSIFICATION"
    cls["B5"], cls["C5"], cls["C6"], cls["C7"] = "MTS", "CLOSE CONTROL", "REGULAR REVIEW", "INFREQUENT REVIEW"
    cls.merge_cells("B5:B7")
    raw = wb.create_sheet("Sheet1")
    raw.append(["Components/Created on", "Components/Product/Reference"])
    raw.sheet_state = "hidden"
    wb.active = 1  # saved with CLASS as the open tab: the viewer must start there, like Excel
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_amc_import_upload_view_export_delete(client):
    from oicas.models import AmcImport
    from oicas.db import session_factory
    data = _amc_workbook()
    login(client, "counter")
    assert client.get("/amc-import").status_code == 200  # everyone can view
    token = csrf(client, "/amc-import")
    r = client.post("/amc-import/upload", data={"csrf": token, "uploaded_by": "X"},
                    files={"file": ("amc.xlsx", data)}, follow_redirects=False)
    assert r.status_code == 403  # upload needs import.run (manager)

    login(client, "manager")
    token = csrf(client, "/amc-import")
    r = client.post("/amc-import/upload", data={"csrf": token, "uploaded_by": "Jovielyn"},
                    files={"file": ("03_AMC Sep-Jul  ABC Analysis.xlsx", data)}, follow_redirects=False)
    assert r.status_code == 303 and "/amc-import?open=" in r.headers["location"]
    iid = int(r.headers["location"].rsplit("=", 1)[1])
    page = client.get("/amc-import").text
    assert f'data-amc-open="{iid}"' in page and "Jovielyn" in page and "AMC Import" in page

    view = client.get(f"/amc-import/{iid}/view").text
    assert "CONSOLIDATED" in view and "CLASS" in view and "Sheet1" not in view  # hidden sheet not shown
    assert 'data-sheet="1"' in view and 'id="amc-sheet-name">CLASS<' in view
    assert re.search(r'class="amc-tab active" data-amc-sheet="1"', view)  # CLASS has no tab colour
    assert re.search(r'class="amc-tab colored" data-amc-sheet="0"[^>]*--tab-bg: #00B050', view)  # green tab
    assert view.index('class="amc-tabbar"') < view.index('id="amc-grid"')  # sheet bar sits above the grid
    grid = client.get(f"/amc-import/{iid}/sheets/0").text
    assert "746" in grid and "0.02%" in grid and "50.00%" in grid  # Excel number formats
    assert "pill" not in grid  # plain text like Excel, not badges
    assert "Acrylic Sheet &lt;b&gt;" in grid  # escaped
    found = client.get(f"/amc-import/{iid}/sheets/0", params={"q": "acrylic"}).text
    assert "8RM05-905" in found and "8RM04-341-1" not in found
    cls = client.get(f"/amc-import/{iid}/sheets/1").text
    assert 'rowspan="3"' in cls  # merged B5:B7
    assert client.get(f"/amc-import/{iid}/sheets/9").status_code == 404

    dl = client.get(f"/amc-import/{iid}/download")
    assert dl.status_code == 200 and dl.content == data and "attachment" in dl.headers["content-disposition"]

    token = csrf(client, "/amc-import")
    r = client.post(f"/amc-import/{iid}/delete", data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    db = session_factory()()
    assert db.get(AmcImport, iid) is None
    db.close()


def test_amc_import_rejects_bad_files(client):
    login(client, "manager")
    token = csrf(client, "/amc-import")
    r = client.post("/amc-import/upload", data={"csrf": token, "uploaded_by": "Me"},
                    files={"file": ("notes.txt", b"hello")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/amc-import"
    r = client.post("/amc-import/upload", data={"csrf": token, "uploaded_by": "Me"},
                    files={"file": ("broken.xlsx", b"not a zip")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/amc-import"
    r = client.post("/amc-import/upload", data={"csrf": token, "uploaded_by": "  "},
                    files={"file": ("amc.xlsx", _amc_workbook())}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/amc-import"


def test_amc_excel_layout_hidden_rows_cols_widths_cf():
    import io

    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Border, Font, PatternFill, Side
    from oicas.services import amc_import
    wb = Workbook()
    ws = wb.active
    ws.title = "RM"
    ws.append(["#", "Code", "Secret", "Class"])
    for i, (code, cl) in enumerate([("A-1", "A"), ("B-2", "B"), ("C-3", "C"), ("D-4", "A")], start=1):
        ws.append([i, code, "hidden col", cl])
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].hidden = True
    ws.row_dimensions[3].hidden = True  # a filtered-out row
    ws.row_dimensions[2].height = 40
    ws.freeze_panes = "C2"
    ws.sheet_view.showGridLines = False
    ws["A1"].fill = PatternFill("solid", fgColor="FBD4B4")
    ws["A1"].font = Font(name="Calibri", size=10, bold=True)
    ws["A1"].border = Border(bottom=Side(style="thin", color="000000"))
    ws.conditional_formatting.add("D2:D5", CellIsRule(operator="equal", formula=['"A"'],
                                                      fill=PatternFill(bgColor="00B050", fill_type="solid")))
    ws.auto_filter.ref = "A1:D5"
    buf = io.BytesIO()
    wb.save(buf)
    sh = amc_import.parse_workbook(buf.getvalue())[0]
    lay = sh["layout"]
    assert lay["colpx"][1] == 210 and lay["colpx"][2] == 0  # B = 30 wide, C hidden
    assert lay["hrows"] == [3] and lay["rowpx"]["2"] == 53 and lay["fr"] == 1 and lay["fc"] == 2 and lay["grid"] is False
    assert lay["filter"] == [1, 1, 5, 4]

    class S:  # the parts of AmcImportSheet that page() reads
        rows, merges, n_cols = sh["rows"], sh["merges"], sh["n_cols"]
        layout, style_grid, style_table = lay, sh["style_grid"], sh["style_table"]
    pg = amc_import.page(S)
    assert [n for n, *_ in pg["rows"]] == [2, 4, 5] and pg["hidden_n"] == 1  # row 3 hidden like Excel
    assert [l["L"] for l in pg["letters"]] == ["A", "B", "D"]  # column C hidden
    assert "background-color:#00B050" in pg["css"] and "background-color:#FBD4B4" in pg["css"]
    assert "border-bottom:1px solid #000000" in pg["css"]
    assert [n for n, *_ in amc_import.page(S, show_hidden=True)["rows"]] == [2, 3, 4, 5]
    # the "A" cells (rows 2 and 5) get the green fill, the others don't
    greens = [i for i, t in enumerate(sh["style_table"]) if "#00B050" in t["c"]]
    assert greens and sh["style_grid"][1][3] in greens and sh["style_grid"][4][3] in greens
    assert sh["style_grid"][2][3] not in greens


def test_amc_tab_colors_real_workbook():
    from pathlib import Path

    from oicas.services.amc_import import active_sheet_name, tab_colors
    f = Path(__file__).resolve().parents[2] / "03_AMC Sep-Jul  ABC Analysis.xlsx"
    if not f.exists():
        pytest.skip("reference workbook not available")
    data = f.read_bytes()
    c = tab_colors(data)
    assert c["CONSOLIDATED"] == "#00B050" and c["Stone ABC Analysis"] == "#FFFF00" and c["List excluded"] == "#FFC000"
    assert "CLASS" not in c and "Demand" not in c
    assert active_sheet_name(data) == "List excluded"
    from oicas.services import amc_import
    sheets = {x["name"]: x for x in amc_import.parse_workbook(data)}
    rm = sheets["RM"]
    assert len(rm["layout"]["hrows"]) == 905 and rm["layout"]["fr"] == 2 and rm["layout"]["fc"] == 2
    assert rm["layout"]["colpx"][2] == 588 and rm["layout"]["grid"] is False  # Description = 84 wide, no gridlines
    assert sheets["Demand"]["layout"]["grid"] is True
    assert not any(0 in x["layout"]["colpx"] for x in sheets.values())  # no hidden columns in this workbook


def test_amc_format_value():
    from oicas.services.amc_import import format_value as f
    assert f(745.7, "0") == "746"
    assert f(0.00024064, "0.00%") == "0.02%"
    assert f(1, "0.00%") == "100.00%"
    assert f(1234567.891, "#,##0.00") == "1,234,567.89"
    assert f(124.28333333333335, "General") == "124.2833333"
    assert f(2025, "General") == "2025"
    assert f(-0.2, "0") == "0"
    assert f(None) == "" and f("AB") == "AB"
