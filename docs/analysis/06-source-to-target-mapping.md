# 06 — Source-to-Target Data Mapping

Target tables are defined in [`backend/oicas/models.py`](../../backend/oicas/models.py). **Owner** says which system is authoritative for a field.

| Source (workbook › sheet › column) | Target table.column | Owner | Transformation |
|---|---|---|---|
| Odoo `product.product.id` | `item.odoo_product_id` | Odoo | stable key; unique |
| W1/W2/W3 code columns (`Code`, `RM CODE`, `Internal Reference`) / Odoo `default_code` | `item.code` | Odoo | trimmed; unique, case-sensitive (DQ-05 for case variants such as `13t01-001`) |
| Odoo `product.product.display_name` / Description | `item.description` | Odoo | – |
| W2 DATA!G / Odoo `uom_id` | `item.uom_name`, `item.uom_odoo_id` | Odoo | alias table `uom_alias` normalises PC/Piece/UN/Unit … (reporting only) |
| W1 family sheet name / AC Material Section | `item.material_section` | OICAS | editable by Inventory Admin; seeded from legacy import |
| W1 AD Plant Location | `item.plant_location` | OICAS | text, validated against `plant_location` list ("1", "1 & 3", …) |
| W2 DATA!J:M JIT list → Master T | `item.remark`, `item.is_jit` | OICAS | – |
| W1 Sheet1 / Demand C:N | `demand_batch`, `demand_line(item_code, month, qty)` | Odoo (imported) | month = first day of month of `Created on` in company TZ; `""` → no row (missing ≠ 0) |
| W1 CLASS matrix, thresholds | `rule_set.params` (JSON, versioned, effective date) | OICAS | seeded as rule set v1 "Legacy 2025-26" |
| W1 family sheet P..AB | `analysis_result.*` | OICAS (calculated) | engine `abc.analyse_family` + `classification.classify` + `amc.amc` |
| W1 CONSOLIDATED AE/AF | `analysis_result.category`, `.interval_days` | OICAS (calc) | – |
| W3 LIST A (date), G (counted by), F (remarks) | `count_session.count_date`, `.counted_by_name`, `count_entry.remarks` | OICAS | one session per (date, counter) on legacy import |
| W3 LIST H:K (WH-1..4) | `count_entry(bucket='WAREHOUSE', slot=1..4, qty)` | OICAS | one row per non-blank cell |
| W3 LIST L:O (PROD-1..4) | `count_entry(bucket='PRODUCTION', slot=1..4, qty)` | OICAS | – |
| W3 LIST D, E | (derived) `reconciliation.phys_wh/phys_prod` | OICAS (calc) | sum of the item's entries on the count date |
| W3 ODOO inv A (DL date) | `inventory_snapshot.taken_at`, `.source='excel_import'` | Odoo (imported) | one snapshot per DL date |
| W3 ODOO inv D, E | `snapshot_line(bucket, qty)` | Odoo | negative values kept and flagged (DQ-09) |
| Odoo `stock.quant` (location_id, quantity) | `snapshot_line` aggregated by location bucket | Odoo | location → bucket via `stock_location.bucket`; unmapped → DQ |
| Odoo `stock.location` | `stock_location(odoo_id, complete_name, usage, bucket)` | Odoo + OICAS mapping | bucket assigned by Admin |
| W3 LIST P, Q | `reconciliation.odoo_wh/odoo_prod` | calc | from the session's linked snapshot (legacy import: the value pasted in LIST) |
| W3 LIST R, S / W2 R, S | `reconciliation.disc_wh/disc_prod` | calc | physical − Odoo |
| W2 U | `reconciliation.has_discrepancy` | calc | with tolerance (default 0) |
| W2 K, L | view `masterlist` (latest finalized count date; + interval) | calc | – |
| W2 PROGRESS-overall | `metrics.overall()` (on demand) | calc | – |
| W2 PROGRESS-weekly | `metrics.weekly()` (on demand) | calc | – |
| Odoo `res.users` (id, login, name, groups) | `app_user(odoo_uid, login, name, role)` | Odoo identity; OICAS role | role from group mapping, else default Viewer |
