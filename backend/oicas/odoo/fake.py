"""In-memory Odoo used for automated tests and local demos (ODOO_MODE=fake).

It honours the same read-only contract as ``LiveOdoo``. The UI shows a permanent
"DEVELOPMENT FIXTURE – NOT PRODUCTION DATA" banner whenever this gateway is active.

``from_database`` re-serves data already in OICAS (imported items and the most recent imported
Odoo snapshot) so demos never display invented stock quantities.
"""
from __future__ import annotations

import fnmatch
from typing import Iterator

from .client import OdooError, assert_read_only

DEMO_USERS = {
    "admin": {"password": "demo", "name": "Demo Administrator", "groups": ["base.group_system", "stock.group_stock_manager"]},
    "manager": {"password": "demo", "name": "Demo Inventory Manager", "groups": ["stock.group_stock_manager"]},
    "counter": {"password": "demo", "name": "Demo Counter", "groups": ["stock.group_stock_user"]},
    "viewer": {"password": "demo", "name": "Demo Viewer", "groups": ["base.group_user"]},
}

WH_LOC = {"id": 8, "complete_name": "WH/Stock", "usage": "internal", "company_id": [1, "Demo Company"],
          "warehouse_id": [1, "WH"], "active": True}
PROD_LOC = {"id": 18, "complete_name": "WH/Pre-Production", "usage": "internal", "company_id": [1, "Demo Company"],
            "warehouse_id": [1, "WH"], "active": True}


M2O_MODEL = {"location_id": "stock.location", "product_id": "product.product"}


def _match(rec: dict, domain: list, data: dict | None = None) -> bool:
    for term in domain:
        if not isinstance(term, (list, tuple)):
            continue  # '&' / '|' operators: fixture domains are simple conjunctions
        field, op, value = term
        v = rec
        parts = field.split(".")
        for i, part in enumerate(parts):
            v = v.get(part) if isinstance(v, dict) else None
            if i < len(parts) - 1 and isinstance(v, (list, tuple)) and data and part in M2O_MODEL:
                v = next((r for r in data[M2O_MODEL[part]] if r.get("id") == v[0]), None)  # follow many2one
        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], int):
            v = v[0]  # many2one
        if op == "=" and v != value:
            return False
        if op == "!=" and v == value:
            return False
        if op == "in" and v not in value:
            return False
        if op == "not in" and v in value:
            return False
        if op == ">=" and not (v is not None and v >= value):
            return False
        if op == "<" and not (v is not None and v < value):
            return False
        if op == "=like" and not fnmatch.fnmatch(str(v), str(value).replace("%", "*")):
            return False
    return True


class FakeOdoo:
    mode = "fake"

    def __init__(self, products=None, locations=None, quants=None, moves=None, users=None, fail: str | None = None,
                 server_version: str = "17.0-fake"):
        self.data = {
            "product.product": list(products or []),
            "stock.location": list(locations if locations is not None else [WH_LOC, PROD_LOC]),
            "stock.quant": list(quants or []),
            "stock.move": list(moves or []),
        }
        self.users = dict(users if users is not None else DEMO_USERS)
        self.fail = fail  # simulate outages in tests: "all", "stock.quant", ...
        self.server_version = server_version
        self.calls: list[tuple[str, str]] = []

    @classmethod
    def from_database(cls) -> "FakeOdoo":
        from sqlalchemy import select

        from ..db import session_scope
        from ..models import InventorySnapshot, Item, SnapshotLine
        products, quants = [], []
        with session_scope() as db:
            items = db.scalars(select(Item).order_by(Item.id)).all()
            ids = {}
            for i, it in enumerate(items, start=1):
                pid = it.odoo_product_id or 100000 + it.id
                ids[it.code] = pid
                products.append({"id": pid, "default_code": it.code, "display_name": f"[{it.code}] {it.description}",
                                 "name": it.description, "uom_id": [1, it.uom_name or "Units"], "active": True,
                                 "type": "product"})
            # Latest *imported* balance per item and bucket (never the fake's own sync output).
            latest: dict[tuple[str, str], float] = {}
            snaps = db.scalars(select(InventorySnapshot).where(InventorySnapshot.source.in_(("excel_import", "legacy_list")))
                               .order_by(InventorySnapshot.taken_at, InventorySnapshot.id)).all()
            for snap in snaps:
                for ln in db.scalars(select(SnapshotLine).where(SnapshotLine.snapshot_id == snap.id)):
                    latest[(ln.item_code, ln.bucket)] = ln.qty
            for (code, bucket), qty in latest.items():
                if code in ids and qty:
                    loc = WH_LOC if bucket == "WAREHOUSE" else PROD_LOC
                    quants.append({"id": len(quants) + 1, "product_id": [ids[code], code],
                                   "location_id": [loc["id"], loc["complete_name"]], "quantity": qty,
                                   "company_id": [1, "Demo Company"]})
        return cls(products=products, quants=quants)

    # -- gateway API ----------------------------------------------------------------------
    def _check(self, model: str, method: str) -> None:
        assert_read_only(method)
        self.calls.append((model, method))
        if self.fail in ("all", model):
            raise OdooError(f"{model}.{method}: simulated outage")

    def version(self) -> dict:
        if self.fail == "all":
            raise OdooError("version: simulated outage")
        return {"server_version": self.server_version, "protocol_version": 1}

    def authenticate(self, login: str, password: str) -> int | None:
        if self.fail == "all":
            raise OdooError("authenticate: simulated outage")
        u = self.users.get(login)
        if u and u["password"] == password:
            return list(self.users).index(login) + 2
        return None

    def user_info(self, uid: int) -> dict:
        login = list(self.users)[uid - 2]
        u = self.users[login]
        return {"uid": uid, "login": login, "name": u["name"], "email": f"{login}@example.invalid", "share": False,
                "active": True, "groups": sorted(u["groups"])}

    def search_read(self, model: str, domain: list, fields: list[str], order: str = "id") -> Iterator[dict]:
        self._check(model, "search_read")
        if model not in self.data:
            raise OdooError(f"unknown model {model}")
        rows = [r for r in self.data[model] if _match(r, domain, self.data)]
        rows.sort(key=lambda r: r.get("id", 0))
        for r in rows:
            yield {k: r.get(k) for k in ["id", *fields]}

    def call(self, model: str, method: str, *args, **kwargs):
        """Generic entry point so tests can prove that write methods are refused."""
        self._check(model, method)
        raise OdooError(f"{model}.{method} not implemented in fake")
