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


def test_logout_revokes_session(client):
    login(client, "admin")
    token = csrf(client)
    client.post("/logout", data={"csrf": token})
    assert client.get("/", follow_redirects=False).status_code == 303
