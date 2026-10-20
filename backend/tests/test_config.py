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


def test_login_needs_no_service_account_but_sync_does():
    gw = LiveOdoo("https://erp.example", "x")  # no sync login / key: constructing for login is fine
    with pytest.raises(OdooError, match="service account is not configured"):
        list(gw.search_read("product.product", [], ["default_code"]))
