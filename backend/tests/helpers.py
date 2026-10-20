from __future__ import annotations

from datetime import date

from oicas.models import Item, ItemFamily, User
from oicas.odoo.fake import PROD_LOC, WH_LOC, FakeOdoo
from oicas.services import rules

PRODUCTS = [
    {"id": 1, "default_code": "A-1", "display_name": "[A-1] Bolt", "name": "Bolt", "uom_id": [1, "Piece"], "active": True},
    {"id": 2, "default_code": "A-2", "display_name": "[A-2] Nut", "name": "Nut", "uom_id": [1, "Piece"], "active": True},
    {"id": 3, "default_code": "A-3", "display_name": "[A-3] Wire", "name": "Wire", "uom_id": [2, "Meter"], "active": True},
    {"id": 4, "default_code": "A-3", "display_name": "[A-3] Wire dup", "name": "Wire dup", "uom_id": [2, "Meter"], "active": True},
    {"id": 5, "default_code": False, "display_name": "No code", "name": "No code", "uom_id": [1, "Piece"], "active": True},
]
OTHER_LOC = {"id": 30, "complete_name": "WH/QC", "usage": "internal", "company_id": [1, "Demo"], "warehouse_id": [1, "WH"],
             "active": True}


def quants():
    return [
        {"id": 1, "product_id": [1, "A-1"], "location_id": [8, "WH/Stock"], "quantity": 100.0, "company_id": [1, "Demo"]},
        {"id": 2, "product_id": [1, "A-1"], "location_id": [18, "WH/Pre-Production"], "quantity": 5.0, "company_id": [1, "Demo"]},
        {"id": 3, "product_id": [2, "A-2"], "location_id": [8, "WH/Stock"], "quantity": -2.0, "company_id": [1, "Demo"]},
        {"id": 4, "product_id": [1, "A-1"], "location_id": [30, "WH/QC"], "quantity": 7.0, "company_id": [1, "Demo"]},
    ]


def moves():
    return [
        {"id": 1, "product_id": [1, "A-1"], "product_uom_qty": 10.0, "create_date": "2025-09-03 02:00:00", "state": "done",
         "raw_material_production_id": 9},
        {"id": 2, "product_id": [1, "A-1"], "product_uom_qty": 5.0, "create_date": "2025-09-30 17:00:00", "state": "done",
         "raw_material_production_id": 9},  # 01:00 on 1 Oct in Manila → October bucket
        {"id": 3, "product_id": [2, "A-2"], "product_uom_qty": 3.0, "create_date": "2025-10-10 02:00:00", "state": "cancel",
         "raw_material_production_id": 9},
    ]


def fake_odoo(**kw) -> FakeOdoo:
    return FakeOdoo(products=PRODUCTS, locations=[WH_LOC, PROD_LOC, OTHER_LOC], quants=quants(), moves=moves(), **kw)


def map_locations(db):
    from sqlalchemy import select

    from oicas.models import StockLocation
    for loc in db.scalars(select(StockLocation)):
        loc.bucket = {8: "WAREHOUSE", 18: "PRODUCTION"}.get(loc.odoo_id)
    db.flush()


def make_user(db, role="manager", login=None) -> User:
    u = User(login=login or role, name=role.title(), role=role)
    db.add(u)
    db.flush()
    return u


def track_items(db, family="RAW MAT"):
    from sqlalchemy import select
    for it in db.scalars(select(Item)):
        it.tracked = True
        it.abc_family = family
        it.plant_location = "1"
        it.material_section = family
        db.add(ItemFamily(item_code=it.code, family=family))
    db.flush()


def today():
    return date.today()


__all__ = ["rules"]
