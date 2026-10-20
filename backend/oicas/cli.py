"""Command line: ``python -m oicas.cli <command>``.

  seed                      default rule set, break-glass admin (if configured)
  import-legacy [DIR]       one-off migration of the reference workbooks (default docs/reference)
  sync [--demand YYYY-MM:N] Odoo inventory sync (and optionally a demand sync for N months)
  odoo-probe                print Odoo version, locations and access check (read-only)
  analyse BATCH START N     run an analysis draft from a demand batch
  worker                    background loop: periodic inventory sync + snapshot retention
  check                     production safety checks
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

from .config import get_settings
from .db import session_scope

log = logging.getLogger("oicas")


def cmd_prepare_db(_):
    """Create the active database (primary for live, secondary for demo) if it doesn't exist yet."""
    import re

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    s = get_settings()
    s.check_database_separation()
    url = make_url(s.active_database_url)
    print(f"mode={s.odoo_mode} → {s.database_role} database ({url.database})")
    if url.get_backend_name() != "postgresql":
        return
    if not re.fullmatch(r"[A-Za-z0-9_]+", url.database or ""):
        raise SystemExit(f"invalid database name {url.database!r}")
    eng = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        if not c.execute(text("select 1 from pg_database where datname = :n"), {"n": url.database}).scalar():
            c.execute(text(f'CREATE DATABASE "{url.database}"'))
            print(f"created database {url.database}")
    eng.dispose()


def cmd_seed(_):
    from .services import auth, rules
    with session_scope() as db:
        rules.ensure_default_rule_set(db)
        auth.ensure_bootstrap_admin(db)
    print("seeded")


def cmd_import_legacy(a):
    from .services import importers
    ref = Path(a.dir) if a.dir else Path(__file__).resolve().parents[2] / "docs" / "reference"
    with session_scope() as db:
        runs = importers.import_reference_set(db, None, ref, a.force)
        for r in runs:
            print(f"import #{r.id} {r.scope['type']}: {r.stats}")


def cmd_sync(a):
    from .engine.amc import Period
    from .odoo.client import gateway_from_settings
    from .services import sync
    gw = gateway_from_settings()
    with session_scope() as db:
        run = sync.run_inventory_sync(db, gw)
        print(f"inventory sync #{run.id}: {run.status} {run.stats} {run.error or ''}")
        if a.demand:
            ym, n = a.demand.split(":")
            y, m = map(int, ym.split("-"))
            d = sync.run_demand_sync(db, gw, Period(date(y, m, 1), int(n)))
            print(f"demand sync #{d.id}: {d.status} {d.stats} {d.error or ''}")
    return 0 if run.status == "success" else 1


def cmd_probe(_):
    from .odoo.client import gateway_from_settings
    gw = gateway_from_settings()
    print("mode:", gw.mode)
    print("version:", gw.version())
    locs = list(gw.search_read("stock.location", [("usage", "=", "internal")], ["complete_name"]))
    print(f"internal locations ({len(locs)}):")
    for loc in locs:
        print(f"  {loc['id']:>6}  {loc['complete_name']}")
    n = sum(1 for _ in gw.search_read("product.product", [], ["default_code"]))
    print("products readable:", n)


def cmd_analyse(a):
    from .engine.amc import Period
    from .services import analysis
    y, m = map(int, a.start.split("-"))
    with session_scope() as db:
        run = analysis.run_analysis(db, None, int(a.batch), Period(date(y, m, 1), int(a.months)))
        print(f"analysis run #{run.id} (draft): {run.stats}")


def cmd_worker(_):
    from .odoo.client import gateway_from_settings
    from .services import rules, sync
    s = get_settings()
    log.info("worker started (%s database); inventory sync every %s min", s.database_role, s.sync_interval_minutes)
    while True:
        if s.is_live and not s.sync_configured:
            log.warning("live mode: Odoo sync service account not configured (ODOO_SYNC_LOGIN / ODOO_SYNC_API_KEY); "
                        "skipping scheduled sync")
            time.sleep(max(1, s.sync_interval_minutes) * 60)
            continue
        try:
            with session_scope() as db:
                run = sync.run_inventory_sync(db, gateway_from_settings())
                log.info("sync #%s %s", run.id, run.status)
                pruned = sync.prune_snapshots(db, int(rules.get_setting(db, "snapshot_retention_days")))
                if pruned:
                    log.info("pruned %s unreferenced snapshots", pruned)
        except Exception:  # keep the worker alive; the failure is logged and visible in sync history
            log.exception("worker iteration failed")
        time.sleep(max(1, s.sync_interval_minutes) * 60)


def cmd_check(_):
    problems = get_settings().check_production_safety()
    for p in problems:
        print("PROBLEM:", p)
    print("ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="oicas")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare-db").set_defaults(fn=cmd_prepare_db)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    s = sub.add_parser("import-legacy")
    s.add_argument("dir", nargs="?")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_import_legacy)
    s = sub.add_parser("sync")
    s.add_argument("--demand", help="YYYY-MM:months, e.g. 2025-09:11")
    s.set_defaults(fn=cmd_sync)
    sub.add_parser("odoo-probe").set_defaults(fn=cmd_probe)
    s = sub.add_parser("analyse")
    s.add_argument("batch")
    s.add_argument("start", help="YYYY-MM")
    s.add_argument("months")
    s.set_defaults(fn=cmd_analyse)
    sub.add_parser("worker").set_defaults(fn=cmd_worker)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
