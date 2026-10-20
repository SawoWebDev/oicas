"""Live data uses the primary database, demo data the secondary one, and they never mix."""
import pytest

from oicas.config import Settings
from oicas.odoo.client import LiveOdoo, OdooError

PRIMARY = "postgresql+psycopg://u:p@db/oicas"
DEMO = "postgresql+psycopg://u:p@db/oicas_demo"


def test_live_mode_uses_primary_database():
    s = Settings(_env_file=None, odoo_mode="live", odoo_url="https://erp.example", odoo_db="x",
                 database_url=PRIMARY, demo_database_url=DEMO)
    assert s.active_database_url == PRIMARY and s.database_role == "primary"
    s.check_database_separation()


def test_demo_mode_uses_secondary_database():
    s = Settings(_env_file=None, odoo_mode="fake", database_url=PRIMARY, demo_database_url=DEMO)
    assert s.active_database_url == DEMO and s.database_role == "demo"


def test_same_database_for_live_and_demo_is_refused():
    s = Settings(_env_file=None, odoo_mode="fake", database_url=PRIMARY, demo_database_url=PRIMARY)
    with pytest.raises(RuntimeError, match="must be different"):
        s.check_database_separation()


def test_live_mode_requires_odoo_url_and_db():
    s = Settings(_env_file=None, odoo_mode="live", odoo_url="", odoo_db="", database_url=PRIMARY,
                 demo_database_url=DEMO)
    with pytest.raises(RuntimeError, match="ODOO_URL"):
        s.check_database_separation()


def test_without_erp_login_live_sync_refuses():
    gw = LiveOdoo("https://erp.example", "x")  # no logged-in user, no unattended account
    with pytest.raises(OdooError, match="no ERP login available"):
        list(gw.search_read("product.product", [], ["default_code"]))


class _RecordingProxy:
    def __init__(self):
        self.calls = []

    def execute_kw(self, db, uid, secret, model, method, args, kwargs):
        self.calls.append((db, uid, secret, model, method))
        return []


def test_sync_reads_with_the_logged_in_users_erp_login():
    gw = LiveOdoo("https://erp.example", "sawo", as_user=(42, "users-own-password"))
    gw._object = _RecordingProxy()
    assert list(gw.search_read("stock.quant", [], ["quantity"])) == []
    assert gw._object.calls == [("sawo", 42, "users-own-password", "stock.quant", "search_read")]


def test_erp_login_path_is_still_read_only():
    from oicas.odoo.client import ReadOnlyViolation
    gw = LiveOdoo("https://erp.example", "sawo", as_user=(42, "pw"))
    gw._object = _RecordingProxy()
    for method in ("write", "create", "unlink", "action_apply_inventory"):
        with pytest.raises(ReadOnlyViolation):
            gw._call("stock.quant", method, [[1]])
    assert gw._object.calls == []  # nothing ever reached Odoo


def test_vault_keeps_secret_in_memory_only_and_forgets():
    from oicas.odoo import vault
    vault.put("sid", 7, "user@sawo.com", "pw", 60)
    c = vault.get("sid")
    assert c.uid == 7 and "pw" not in repr(c)
    vault.drop("sid")
    assert vault.get("sid") is None
    vault.put("old", 7, "u", "pw", -1)
    assert vault.get("old") is None  # expired with the session
