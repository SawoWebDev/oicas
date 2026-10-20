# OICAS Architecture

## Stack

| Layer | Choice | Why |
|---|---|---|
| Web UI | Server-rendered Jinja2 + Bootstrap 5.3 + Bootstrap Icons + htmx + Chart.js (all vendored under `static/vendor`) | Same design system as SAWO's *General Automation System*; works on the plant LAN without CDN access; no JS build step |
| Backend | Python 3.12, FastAPI | One process serves pages and file exports; typed and fast |
| Persistence | PostgreSQL 16 via SQLAlchemy 2 + Alembic (SQLite for tests) | Relational integrity, transactions, migrations |
| Odoo integration | External API (XML-RPC `/xmlrpc/2/*`) behind a read-only gateway | Supported on Odoo 14–18 (and 19); no direct DB access |
| Background jobs | `worker` container: periodic inventory sync and snapshot retention | Keeps the web process stateless |
| Exports | openpyxl (Excel), ReportLab (PDF) | No external services |
| Deployment | Docker Compose (`db`, `web`, `worker`) | Matches the existing GAS deployment pattern |

## Layers

```
web/ (routes, templates)  ──►  services/ (DB + workflow)  ──►  engine/ (pure calculations)
                                    │
                                    └──►  odoo/ (read-only gateway: LiveOdoo | FakeOdoo)
```

* **`engine/`** holds the pure, deterministic functions (AMC, ABC, classification, reconciliation, metrics, scheduling). Every function documents the Excel formula it reproduces, and the Excel-parity tests target it directly. Nothing else computes an official number.
* **`services/`** is the only layer that touches the database: sync, analysis runs, counting, reconciliation, the masterlist dataset (`inventory.build`), reports, exports, importers, audit and data quality.
* **`services/inventory.build()`** is the single join of items, the approved analysis, the latest reconciliation and the schedule. The dashboard, masterlist, schedule, progress KPIs and most reports all use it, so they always agree.
* **`services/reports.py`** defines the 16 reports. The screen, the Excel export and the PDF export render the *same* `ReportResult` object.

## Data model (main tables)

| Table | Purpose | Mutability |
|---|---|---|
| `item`, `item_family`, `stock_location`, `uom_alias` | Master data (Odoo-owned + OICAS-owned columns) | updated by sync / authorised edits (audited) |
| `sync_run`, `inventory_snapshot`, `snapshot_line`, `snapshot_quant` | Odoo synchronisation log and immutable stock snapshots | append-only |
| `demand_batch`, `demand_line` | Monthly demand (from Odoo or Excel) | append-only |
| `rule_set` | Versioned calculation parameters + classification matrix, with effective date | append-only (new version per change) |
| `analysis_run`, `analysis_result` | AMC/ABC/movement results per item and family | append-only; status draft → approved → superseded |
| `count_plan`, `count_plan_item` | Cycle-count planning and assignment | status changes audited |
| `count_session`, `count_entry` | Physical counts; entries immutable after submission, corrections supersede | append-only after submit |
| `reconciliation`, `discrepancy_note` | Physical vs Odoo per item and count date; review workflow | recalculation supersedes; history kept |
| `dq_exception`, `audit_log`, `report_run` | Governance | append-only |
| `app_user`, `auth_session`, `app_setting` | Access and settings | audited |

## Reproducibility

Each reconciliation stores its snapshot id and rule-set id. Each analysis run stores its demand batch, period and rule-set id. Each export stores its parameters, data versions and the file's SHA-256. Old Odoo snapshots are pruned only when nothing references them (`snapshot_retention_days`).

## Security

* Login with Odoo: the credentials are checked server-side with `common.authenticate`, and the password is never stored. Odoo groups map to OICAS roles (`viewer < counter < manager < admin`) through a configurable mapping. Portal users and inactive users are refused. Failed attempts are throttled (5 per 15 minutes per login and IP).
* Sessions are server-side: a random cookie token whose SHA-256 is stored, HttpOnly + SameSite=Lax, Secure in production, with absolute and idle expiry. Sessions can be revoked, and deactivating a user revokes theirs.
* Every route declares its required permission. CSRF tokens are required on every POST. The CSP has `script-src 'self'` and no inline scripts. `X-Frame-Options: DENY`; HTML responses are `no-store`.
* The Odoo gateway only allows `search_read`, `read`, `search`, `search_count`, `fields_get` and `check_access_rights`. Anything else raises `ReadOnlyViolation` before any network call.
* `APP_ENV=production` refuses to start with a default secret, the fake Odoo, insecure cookies or SQLite.
