# 10 — Unresolved Decisions

Each decision has a default implemented in OICAS so that work isn't blocked. Every default is a **configurable, versioned rule-set parameter** (System Configuration → Rule sets), so the business can change it without a code change. Decisions marked ⚠ change results compared with the legacy workbook and need business approval.

| ID | Question | Evidence | Implemented default | Parameter | Owner to confirm |
|---|---|---|---|---|---|
| UD-01 ⚠ | Should ABC accumulate in **demand-descending** order over the **full** family total (RM and List excluded currently don't)? | DQ-01, DQ-02. 9/11 sheets are sorted, which suggests that's the intent | Descending total, tie → code asc; full total | `abc.ordering = "demand_desc"` (alt. `legacy_sheet_order` for parity replay only) | Inventory / Planning manager |
| UD-02 | AMC denominator: months **with records** (legacy) or **all months in the period**? | F-13, DQ-22 | legacy (months with records) | `amc.method = "recorded_months"` (alt. `period_months`) | Planning |
| UD-03 | Frequency % divisor: fixed 11 or number of months in the selected period? | F-09 | months in selected period (= 11 for the legacy period) | derived from `analysis_run.period` | Planning |
| UD-04 | Scheduling of never-counted items | Master L blank for 5,024 items | due on the analysis approval date (immediately due), prioritised by action (CLOSE CONTROL first) | `schedule.never_counted = "due_now"` | Warehouse supervisor |
| UD-05 | "# counted" and weekly completion are all-time and not de-duplicated. Should completion be **per cycle** (counted within the current interval)? | F-24, F-25 | legacy all-time distinct items for overall; weekly counts distinct items per week; completion = cumulative distinct items ÷ #items | `metrics.completion_basis = "all_time"` (alt. `current_cycle`) | Inventory manager |
| UD-06 | Discrepancy tolerance | F-22 shows 94.99999-style float values | 0 (exact, legacy), with 1e-6 float noise ignored | `reconciliation.abs_tolerance = 0` | Inventory manager |
| UD-07 | Meaning of WH-1..4 / PROD-1..4 columns (plants 1–4, bins, or count rounds?) | Christine counts mostly into WH-3; plant 3 is the most common location | treated as **sub-location slots 1..4** within the bucket; rounds are separate (`round`) | `count.slots = ["1","2","3","4"]` | Warehouse supervisor |
| UD-08 | Which Odoo stock locations make up **WAREHOUSE** and **PRE-PRODUCTION** | ODOO inv only has two totals | Admin maps each internal location to a bucket. Unmapped locations are excluded and reported | `stock_location.bucket` | Odoo admin + warehouse |
| UD-09 | Odoo version, auth method (password / API key / OAuth provider) and groups → OICAS roles | environment not reachable from the build machine | XML-RPC `authenticate` server-side (password or API key, never stored). Group mapping configurable | `ODOO_*` env, `auth.group_role_map` | IT / Odoo admin |
| UD-10 | Code present in several families: which family owns it? | DQ-03 | `item.material_section` (app-owned) chooses the primary family. Results for other families are kept and flagged | – | Planning |
| UD-11 | Demand month bucketing timezone | Odoo stores UTC | `Asia/Manila` | `APP_TIMEZONE` | IT |
| UD-12 | Should the "Normal Moving Inventory (NMI)" row in CLASS be used? | CLASS row 14 has no category | ignored | – | Planning |
| UD-13 | Snapshot staleness threshold for finalising counts | – | 24 h | `odoo.stale_after_hours` | Inventory manager |
