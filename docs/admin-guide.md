# OICAS Administrator & Deployment Guide

## Deploy (Docker Compose)

```bash
git clone https://github.com/arnielmontero/Odoo-Inventory-Control-Analytics-System.git
cd Odoo-Inventory-Control-Analytics-System
cp .env.example .env          # set SECRET_KEY, POSTGRES_PASSWORD, ODOO_* (see docs/odoo-integration.md)
docker compose up -d --build  # db + web (port OICAS_PORT, default 8086) + worker
docker compose exec web python -m oicas.cli check       # production safety check
docker compose exec web python -m oicas.cli odoo-probe  # read-only Odoo connectivity check
```

`web` applies database migrations (`alembic upgrade head`) and seeds the default rule set on every start. `worker` runs the Odoo inventory sync every `SYNC_INTERVAL_MINUTES` and prunes unreferenced old snapshots.

For production: `APP_ENV=production`, `ODOO_MODE=live`, `COOKIE_SECURE=true`, and serve behind HTTPS (e.g. the existing reverse proxy). The app refuses to start in production with unsafe settings.

## Live and demo databases

`ODOO_MODE` in `.env` selects both the Odoo connection and the database:

| `ODOO_MODE` | Database | Login | Data |
|---|---|---|---|
| `live` | **primary** `oicas` (`DATABASE_URL`) | real Odoo username/email + password (checked by Odoo) | live data only |
| `fake` | **secondary** `oicas_demo` (`DEMO_DATABASE_URL`) | demo accounts `admin`/`manager`/`counter`/`viewer`, password `demo` | demo/training data only |

Switch with `docker compose up -d` after editing `.env`. The containers are recreated and connect to the other database; each database keeps its own users, sessions and history. On start, `web` creates the selected database if it's missing and applies migrations. OICAS refuses to start if both URLs point at the same database. The header shows **LIVE · primary DB** or **DEMO · secondary DB** on every page.

Live mode needs only `ODOO_URL` and `ODOO_DB`. There is no API key and no service account. Users log in with their **ERP login**, and *Sync Odoo now* reads Odoo **as that user**, with their own Odoo access rights. The ERP password is held only in the web server's memory for the length of the session; it's never written to the database or disk, and it's dropped on logout or expiry. After a restart, the sync button asks for the ERP password once. Optionally, `ODOO_SYNC_LOGIN` / `ODOO_SYNC_PASSWORD` enable an unattended hourly sync by the worker; leave them empty to sync from the screen. Keep `web` as a single process: the in-memory credential store isn't shared between processes.

Back up both databases: `pg_dump -U oicas -Fc oicas` and `pg_dump -U oicas -Fc oicas_demo`.

## One-off migration of the Excel history

*System Configuration → Imports → Migrate legacy workbooks*, or:

```bash
docker compose exec web python -m oicas.cli import-legacy      # reads /docs/reference (mounted read-only)
```

This imports items, families, plant and section, the demand pivot, the legacy ABC/AMC results (approved as the baseline analysis run), the Odoo downloads, every COUNTED LIST line (as finalized sessions) and their reconciliations. Each file can only be imported once (SHA-256 check). The migration is verified by `tests/parity/test_legacy_migration.py`.

## First-time configuration checklist
1. *Synchronization History → Sync Odoo now*.
2. *System Configuration → Odoo locations*: map each internal location to WAREHOUSE / PRODUCTION / IGNORE, then sync again.
3. *Settings*: check `auth group role map`, plant locations, material sections, ABC families and the staleness threshold.
4. *Rule sets*: review v1. Decisions marked ⚠ in `docs/analysis/10-unresolved-decisions.md` are set here and need business sign-off.
5. *Data Quality*: work through open exceptions (unknown codes, missing plant location, duplicate codes, …).

## Rule sets (calculation configuration)
Rule sets are versioned and never edited. Saving creates version *n+1* with an effective date. Parameters:

| Parameter | Default | Legacy-replay value |
|---|---|---|
| ABC qty thresholds | A < 80 %, C ≥ 95 % | same |
| ABC frequency thresholds | A > 80 %, C ≤ 50 % | same |
| ABC ordering | rank by total demand | keep sheet order |
| AMC method | average of months with demand | same |
| Discrepancy tolerance | 0 | 0 |
| Uncounted location | not counted (no variance) | treat as 0 |
| Missing Odoo balance | missing (no variance) | treat as 0 |
| Never-counted items | due now | unscheduled |
| Classification matrix | CLASS sheet (AA…CC → action/class/30-90-180 days) | same |

## Backups and restore

```bash
# backup (daily via cron / Task Scheduler)
docker compose exec -T db pg_dump -U oicas -Fc oicas > backups/oicas_$(date +%F).dump
# restore into an empty database
docker compose exec -T db pg_restore -U oicas -d oicas --clean --if-exists < backups/oicas_YYYY-MM-DD.dump
```
Keep backups off the server. Exports are regenerated from the database and don't need backing up.

## Operations
* Health: `GET /healthz` (Docker healthcheck).
* Logs: `docker compose logs -f web worker`.
* Upgrade: `git pull && docker compose up -d --build` (migrations run automatically).
* Tests: `docker build --build-arg INSTALL_DEV=true -t oicas-dev backend && docker run --rm -v "$PWD:/repo" -w /repo/backend oicas-dev python -m pytest -q`.
* Users: users appear after their first Odoo login. Change roles, lock a role against the group mapping, deactivate users or revoke sessions under *System Configuration → Users & roles*.
* Break-glass admin: set `BOOTSTRAP_ADMIN_LOGIN/PASSWORD`, restart, and log in with *Emergency administrator login*. Remove the values afterwards.
