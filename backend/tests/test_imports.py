"""Import Center: templates, dry run, all-or-nothing validation, items not in Odoo, book balances,
count lines and changing an item's code when it is encoded in Odoo later."""
from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from oicas.db import Base, make_engine, session_factory, set_engine
from oicas.models import CountEntry, CountSession, DqException, Item, Reconciliation
from oicas.services import counting, imports, rules, sync

from .helpers import PRODUCTS, fake_odoo, make_user, map_locations, track_items


@pytest.fixture
def db():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    set_engine(eng)
    s = session_factory()()
    rules.ensure_default_rule_set(s)
    gw = fake_odoo()
    sync.run_inventory_sync(s, gw)
    map_locations(s)
    sync.run_inventory_sync(s, gw)
    track_items(s)
    yield s
    s.close()


def filled(kind: str, rows: list[list]) -> io.BytesIO:
    """Start from the downloadable template (keeps its example row) and append data rows."""
    wb = load_workbook(io.BytesIO(imports.template_workbook(kind)))
    ws = wb["DATA"]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@pytest.mark.parametrize("kind", list(imports.TEMPLATES))
def test_every_template_downloads_with_instructions(kind):
    wb = load_workbook(io.BytesIO(imports.template_workbook(kind)))
    assert wb.sheetnames == ["DATA", "HOW TO"]
    assert [c.value for c in wb["DATA"][1]] == imports.TEMPLATES[kind]["columns"]


def test_untouched_template_imports_nothing(db):
    u = make_user(db)
    res = imports.import_items(db, u, filled("items", []), "t.xlsx", dry_run=True)
    assert res.ok and res.rows == 0


def test_items_not_in_odoo_get_temporary_code(db):
    u = make_user(db)
    rows = [["", "Gasket - silicone 5mm", "Piece", "Consumables", "Excluded list", "3", "", "yes"],
            ["", "Foam tape", "Roll", "Consumables", "", "1", "JIT", ""],
            ["A-1", "ignored: Odoo owns the description", "", "RAW MAT", "", "1 & 3", "", ""]]
    dry = imports.import_items(db, u, filled("items", rows), "items.xlsx", dry_run=True)
    assert dry.ok and dry.created == 2 and dry.updated == 1
    assert db.scalars(select(Item).where(Item.code.like("NC-%"))).first() is None  # dry run saved nothing
    res = imports.import_items(db, u, filled("items", rows), "items.xlsx")
    assert res.ok
    nc = {i.code: i for i in db.scalars(select(Item).where(Item.code.like("NC-%")))}
    assert set(nc) == {"NC-00001", "NC-00002"}
    assert nc["NC-00001"].tracked and nc["NC-00001"].odoo_product_id is None and nc["NC-00002"].is_jit
    a1 = db.scalars(select(Item).where(Item.code == "A-1")).first()
    assert a1.description == "Bolt" and a1.plant_location == "1 & 3"
    assert ("not_in_odoo", "NC-00001") in {(e.kind, e.ref) for e in db.scalars(select(DqException))}


def test_invalid_file_is_rejected_completely(db):
    u = make_user(db)
    rows = [["X-NEW", "Valid row", "Piece", "", "", "1", "", ""],
            ["X-BAD", "Bad plant", "Piece", "", "", "9", "", ""]]
    res = imports.import_items(db, u, filled("items", rows), "bad.xlsx")
    assert not res.ok and "PLANT LOCATION" in res.errors[0]
    db.rollback()
    assert db.scalars(select(Item).where(Item.code == "X-NEW")).first() is None


def _import_nc_item(db, u):
    imports.import_items(db, u, filled("items", [["", "Gasket", "Piece", "", "RAW MAT", "1", "", "yes"]]), "i.xlsx")
    return "NC-00001"


def test_book_balance_used_when_item_not_in_odoo(db):
    u = make_user(db)
    code = _import_nc_item(db, u)
    d = date.today()
    res = imports.import_book_balances(db, u, filled("book_balances", [[d.isoformat(), code, 120, ""]]), "b.xlsx")
    assert res.ok, res.errors
    s = counting.create_session(db, u, d, "Christine A")
    counting.add_entry(db, u, s.id, code, "WAREHOUSE", 118)
    counting.submit(db, u, s.id)
    counting.finalize(db, u, s.id)
    rc = counting.current_reconciliation(db, code, d)
    assert rc.balance_source == "book" and rc.odoo_wh == 120 and rc.disc_wh == -2 and rc.odoo_prod is None


def test_book_balance_dated_after_count_is_not_used(db):
    u = make_user(db)
    code = _import_nc_item(db, u)
    d = date.today()
    s = counting.create_session(db, u, d - timedelta(days=5), "X")
    counting.add_entry(db, u, s.id, code, "WAREHOUSE", 10)
    counting.submit(db, u, s.id)
    counting.finalize(db, u, s.id)
    imports.import_book_balances(db, u, filled("book_balances", [[d.isoformat(), code, 10, ""]]), "b.xlsx")
    rc = counting.current_reconciliation(db, code, d - timedelta(days=5))
    assert rc.status == "odoo_missing" and rc.balance_source != "book"


def test_book_balance_import_refreshes_unverified_counts(db):
    u = make_user(db)
    code = _import_nc_item(db, u)
    d = date.today()
    s = counting.create_session(db, u, d, "X")
    counting.add_entry(db, u, s.id, code, "WAREHOUSE", 50)
    counting.submit(db, u, s.id)
    counting.finalize(db, u, s.id)
    assert counting.current_reconciliation(db, code, d).status == "odoo_missing"
    res = imports.import_book_balances(db, u, filled("book_balances", [[d.isoformat(), code, 50, ""]]), "b.xlsx")
    assert res.details["reconciliations_refreshed"] == 1
    assert counting.current_reconciliation(db, code, d).status == "accurate"


def test_book_balance_requires_known_item(db):
    res = imports.import_book_balances(db, make_user(db), filled("book_balances", [[date.today().isoformat(), "ZZZ", 1, ""]]),
                                       "b.xlsx")
    assert not res.ok and "unknown item ZZZ" in res.errors[0]


def test_count_lines_create_submitted_sessions_with_book_balance(db):
    u = make_user(db)
    code = _import_nc_item(db, u)
    d = date.today().isoformat()
    rows = [[d, code, "Christine A", "", "", 118, "", "", "", "", "", "bin 3", 120, ""],
            [d, "A-1", "Christine A", 60, 40, "", "", "", "", "", "", "", "", ""],
            [d, "A-2", "Giniemark", "", "", "", "", "", "", "", "", "", "", ""]]  # no quantity → skipped
    res = imports.import_count_lines(db, u, filled("count_lines", rows), "c.xlsx")
    assert res.ok, res.errors
    assert res.created == 3 and res.skipped == 1 and res.details["sessions"] == 1
    s = db.scalars(select(CountSession).where(CountSession.source == "excel_upload")).one()
    assert s.status == "submitted" and len(s.entries) == 3
    counting.finalize(db, u, s.id)
    assert counting.current_reconciliation(db, code, date.today()).disc_wh == -2
    assert counting.current_reconciliation(db, "A-1", date.today()).phys_wh == 100


def test_count_lines_validation(db):
    u = make_user(db)
    future = (date.today() + timedelta(days=2)).isoformat()
    rows = [[future, "A-1", "X", 1, "", "", "", "", "", "", "", "", "", ""],
            [date.today().isoformat(), "A-1", "X", "abc", "", "", "", "", "", "", "", "", "", ""],
            [date.today().isoformat(), "NOPE", "X", 1, "", "", "", "", "", "", "", "", "", ""]]
    res = imports.import_count_lines(db, u, filled("count_lines", rows), "c.xlsx")
    text = " ".join(res.errors)
    assert "future" in text and "not a number" in text and "unknown item NOPE" in text
    assert db.scalars(select(CountSession)).first() is None


def test_rekey_when_item_is_encoded_in_odoo_later(db):
    u = make_user(db)
    code = _import_nc_item(db, u)
    d = date.today()
    imports.import_book_balances(db, u, filled("book_balances", [[d.isoformat(), code, 5, ""]]), "b.xlsx")
    s = counting.create_session(db, u, d, "X")
    counting.add_entry(db, u, s.id, code, "WAREHOUSE", 5)
    counting.submit(db, u, s.id)
    counting.finalize(db, u, s.id)
    # the item is now encoded in Odoo as A-9; the next sync creates an (empty) item for it
    gw = fake_odoo()
    gw.data["product.product"] = PRODUCTS + [{"id": 9, "default_code": "A-9", "display_name": "[A-9] Gasket",
                                              "name": "Gasket (Odoo)", "uom_id": [1, "Piece"], "active": True}]
    sync.run_inventory_sync(db, gw)
    it = imports.rekey_item(db, u, code, "A-9")
    assert it.code == "A-9" and it.odoo_product_id == 9 and it.tracked
    assert db.scalars(select(Item).where(Item.code == code)).first() is None
    assert db.scalars(select(CountEntry).where(CountEntry.item_code == "A-9")).first() is not None
    assert counting.current_reconciliation(db, "A-9", d) is not None
    assert ("not_in_odoo", "A-9") not in {(e.kind, e.ref) for e in db.scalars(
        select(DqException).where(DqException.status == "open"))}


def test_rekey_refuses_existing_code_with_history(db):
    u = make_user(db)
    code = _import_nc_item(db, u)
    s = counting.create_session(db, u, date.today(), "X")
    counting.add_entry(db, u, s.id, "A-1", "WAREHOUSE", 1)
    with pytest.raises(ValueError):
        imports.rekey_item(db, u, code, "A-1")


def test_reconciliation_records_odoo_source(db):
    u = make_user(db)
    s = counting.create_session(db, u, date.today(), "X")
    counting.add_entry(db, u, s.id, "A-1", "WAREHOUSE", 100)
    counting.submit(db, u, s.id)
    counting.finalize(db, u, s.id)
    rc = db.scalars(select(Reconciliation).where(Reconciliation.item_code == "A-1")).first()
    assert rc.balance_source == "odoo"
