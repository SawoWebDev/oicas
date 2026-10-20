# OICAS — Odoo Inventory Control & Analytics System

OICAS replaces the manual Excel workflow (AMC/ABC analysis → Inventory Masterlist → Counted List → progress dashboards) with one connected web application. The application reads inventory from Odoo, schedules cycle counts, records physical counts, reconciles them against Odoo and produces the official reports.

> Status: under construction. See [TRACKER.md](TRACKER.md) for live progress.

## Repository guide

| Path | What it holds |
|---|---|
| [docs/Task.md](docs/Task.md) | Master development brief (the requirements) |
| [docs/reference/](docs/reference/) | The four legacy Excel workbooks (private business data; keep the repository private) |
| [docs/analysis/](docs/analysis/) | Phase-1 reverse-engineering: workbook inventory, data dictionary, formula register, dependency map, process map, source-to-target mapping, report catalog, business rules, data-quality register, unresolved decisions |
| [TRACKER.md](TRACKER.md) | Phase checklist and change log |
| [tools/](tools/) | Excel analysis scripts used for Phase 1 |

## Working agreement

1. Work on `main` only through small commits. Record every change in the **Change Log** of [TRACKER.md](TRACKER.md).
2. Business rules come from [docs/analysis/08-business-rules.md](docs/analysis/08-business-rules.md). Don't change a calculation without updating the formula register and the parity tests.
3. Open questions go to [docs/analysis/10-unresolved-decisions.md](docs/analysis/10-unresolved-decisions.md); don't guess silently.
4. Never commit secrets (`.env`), production exports or database dumps.
