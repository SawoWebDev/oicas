# OICAS — Project Tracker

Live checklist and change log for the build described in [docs/Task.md](docs/Task.md).
Status legend: ✅ done & tested · 🟡 in progress · 🧪 built, not yet tested · ⛔ blocked (needs input/environment) · ⬜ not started

**How to use:** update the status column when work moves. Add a row to the **Change Log** for every merged change (date, area, summary, commit). Decisions that need business sign-off live in [docs/analysis/10-unresolved-decisions.md](docs/analysis/10-unresolved-decisions.md).

---

## Phase checklist

| Phase | Item | Status | Notes |
|---|---|---|---|
| 1 Excel reverse-engineering | Workbook inventory | ✅ | [01](docs/analysis/01-workbook-inventory.md) |
| | Data dictionary | ✅ | [02](docs/analysis/02-data-dictionary.md) |
| | Formula & calculation register | ✅ | [03](docs/analysis/03-formula-register.md) |
| | Cross-workbook dependency map | ✅ | [04](docs/analysis/04-dependency-map.md) |
| | Current-state process map + target workflow | ✅ | [05](docs/analysis/05-process-map.md) |
| | Source-to-target mapping | ✅ | [06](docs/analysis/06-source-to-target-mapping.md) |
| | Report catalog | ✅ | [07](docs/analysis/07-report-catalog.md) |
| | Business rules register | ✅ | [08](docs/analysis/08-business-rules.md) |
| | Data quality register | ✅ | [09](docs/analysis/09-data-quality-register.md) |
| | Unresolved decisions | ✅ | [10](docs/analysis/10-unresolved-decisions.md): 13 open, defaults implemented |
| 2 Architecture & DB | Architecture doc | ⬜ | |
| | Data model + migrations | ⬜ | |
| | Central calculation engine | ⬜ | |
| 3 Odoo auth & read-only integration | Read-only XML-RPC client (method whitelist) | ⬜ | |
| | Login with Odoo (server-side) | ⬜ | |
| | Sync: products, UoM, locations, quants → snapshot | ⬜ | |
| | Verification against the **real** Odoo instance | ⛔ | Needs Odoo URL/DB/service credentials (UD-09) |
| 4 Masterlist & data quality | Masterlist screen, filters, item detail | ⬜ | |
| | DQ exception detection & screen | ⬜ | |
| | Legacy workbook importer | ⬜ | |
| 5 Counting & scheduling | Count plans, sessions, entries, corrections, recounts | ⬜ | |
| | Scheduling engine (due/overdue/upcoming) | ⬜ | |
| 6 Reconciliation | Discrepancy engine, review workflow | ⬜ | |
| 7 AMC / ABC / movement | Analysis runs, approval, comparison | ⬜ | |
| 8 Dashboard & reports | Dashboard, 16 reports, Excel/PDF export | ⬜ | |
| 9 Security & hardening | RBAC, CSRF, sessions, audit, backups | ⬜ | |
| 10 Validation & deployment | Excel-parity tests, e2e tests, Docker deploy, docs | ⬜ | |

---

## Change Log

| Date | Area | Change | By |
|---|---|---|---|
| 2026-10-20 | Repo | Moved Task.md and reference workbooks into `docs/`; created tracker, README, Phase-1 analysis artifacts | Claude Code |
