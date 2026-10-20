# OICAS — Project Tracker

Live checklist and change log for the build described in [docs/Task.md](docs/Task.md).
Status legend: ✅ done & tested · 🟡 in progress · 🧪 built, not yet tested · ⛔ blocked (needs input or environment) · ⬜ not started

**How to use:** update the status column when work moves. Add a row to the **Change Log** for every change you push (date, area, summary). Decisions that need business sign-off live in [docs/analysis/10-unresolved-decisions.md](docs/analysis/10-unresolved-decisions.md).

---

## Phase checklist

| Phase | Item | Status | Notes |
|---|---|---|---|
| 1 Excel reverse-engineering | Workbook inventory, data dictionary, formula register, dependency map, process map, mapping, report catalog, business rules, DQ register, unresolved decisions | ✅ | [docs/analysis/](docs/analysis/) |
| 2 Architecture & DB | Architecture | ✅ | [docs/architecture.md](docs/architecture.md) |
| | Data model + Alembic migration | ✅ | `backend/oicas/models.py`, `alembic/versions/0001` (tested on SQLite and PostgreSQL 16) |
| | Central calculation engine | ✅ | `backend/oicas/engine/`; 14 formula-parity tests |
| 3 Odoo auth & read-only integration | Read-only XML-RPC gateway (method whitelist, retries, pagination) | ✅ | tested with the fixture; write methods refused |
| | Login with Odoo (server-side, group → role, throttling) | ✅ | |
| | Sync: locations, products, quants → snapshots; MO demand | ✅ | fixture-tested, incl. failure rollback and staleness |
| | Live/demo database separation (primary `oicas` ↔ secondary `oicas_demo`, chosen by ODOO_MODE) | ✅ | config tests; refuses identical URLs |
| | Reach real Odoo (erp.sawo.com, Odoo 17.0 Enterprise) | ✅ | version check 2026-10-20 |
| | First live login with a SAWO Odoo account | 🟡 | ready; needs a user to log in |
| | First live sync | 🟡 | ready: a manager presses *Sync Odoo now* with their ERP login (no API key) |
| 4 Masterlist & data quality | Masterlist, filters, sort, item detail, editable OICAS-owned fields | ✅ | |
| | DQ detection (sync, import, item scan) and review screen | ✅ | 19 exception kinds |
| | Legacy workbook migration | ✅ | migration parity: 6,086 items, 34 explained differences |
| | Data Import center: templates + dry run for items not in Odoo (temporary NC codes), book balances, count lines, demand; change item code when encoded in Odoo | ✅ | `services/imports.py`, 18 tests |
| 5 Counting & scheduling | Plans, assignment, count sheets (Excel/PDF), sessions, entries, upload, submit, corrections, recounts, idempotency | ✅ | |
| | Scheduling (due / overdue / upcoming / never counted, priority) | ✅ | |
| 6 Reconciliation | Engine, snapshot linking, stale-snapshot guard, review workflow | ✅ | |
| 7 AMC / ABC / movement | Analysis runs (draft → approve), demand sync/upload, run comparison | ✅ | |
| 8 Dashboard & reports | Dashboard with drill-downs, 16 reports, Excel/PDF export with SAWO logo | ✅ | export = screen test |
| 9 Security & hardening | RBAC, CSRF, CSP, sessions, audit log, production safety check, backups doc | ✅ | external penetration test not done |
| 10 Validation & deployment | Parity tests, service and web tests (65 passing) | ✅ | [docs/parity-results.md](docs/parity-results.md) |
| | Docker Compose deployment (db/web/worker), docs | ✅ | [docs/admin-guide.md](docs/admin-guide.md) |
| | User acceptance testing with inventory staff | ⬜ | needs business users |
| | Business sign-off of ⚠ decisions UD-01, UD-14 | ⛔ | Inventory / planning managers |
| Later | AI-assisted explanations (Task.md §21) | ⬜ | Not started. It must only use deterministic, stored results |

---

## Change Log

| Date | Area | Change |
|---|---|---|
| 2026-10-20 | Repo | Moved Task.md and reference workbooks into `docs/`; created tracker, README, Phase-1 analysis |
| 2026-10-20 | Engine | AMC, ABC, classification, reconciliation, metrics, scheduling + Excel-parity tests |
| 2026-10-20 | Backend | Models, migration, read-only Odoo gateway, sync, counting, analysis, importers, 16 reports, Excel/PDF exports |
| 2026-10-20 | Migration | Legacy workbook import with end-to-end parity; found DQ-23 (blank count lines) and DQ-24 (stale Masterlist copies); added UD-14..UD-16 |
| 2026-10-20 | UI | Web app in the General Automation System design (Bootstrap 5, SAWO logo), dashboard, all modules |
| 2026-10-20 | Deploy | Docker Compose (PostgreSQL, web, worker), `.env.example`, user/admin/Odoo guides |
| 2026-10-20 | Deploy | Live data → primary DB `oicas`, demo data → secondary DB `oicas_demo` (by ODOO_MODE); Odoo login works without the sync account; worker skips sync until it is configured; moved existing demo data to `oicas_demo` and emptied the primary |
| 2026-10-20 | Odoo | Removed API key / service-account requirement: sync runs with the logged-in user's ERP login (password in memory only, asked again after restart); optional unattended login for the worker; erp.sawo.com is read-only (whitelist enforced) |
| 2026-10-20 | Imports | Data Import page with Excel templates and dry run for data not in Odoo; book-balance fallback in reconciliation (`balance_source`, migration 0002); "Change item code" moves history when an item is encoded in Odoo; DQ kind `not_in_odoo` |
