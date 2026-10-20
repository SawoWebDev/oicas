# 07 — Report Catalog

Every report is a `ReportDefinition` in [`backend/oicas/services/reports.py`](../../backend/oicas/services/reports.py). The screen, Excel export and PDF export render the **same** dataset object, so their values cannot diverge. Each export records a `report_run` row: parameters, snapshot id, analysis run id, rule-set version, row count and SHA-256 of the file.

| # | Key | Report | Legacy equivalent | Main filters | Data source |
|---|---|---|---|---|---|
| 1 | `masterlist` | Inventory Masterlist | W2 Master | section, plant, class, action, status, search | items + current analysis + latest reconciliation |
| 2 | `count_sheet` | Inventory Count Sheet (printable) | e-mailed count form | plan, section, plant, location bucket | count plan items |
| 3 | `physical_count` | Physical Inventory Count Report | W3 LIST | date range, counter, session status | count entries + sessions |
| 4 | `reconciliation` | Odoo vs Physical Reconciliation | W2 M:S | date range, bucket, status | reconciliations |
| 5 | `discrepancies` | Inventory Discrepancy Report | W2 filter U=1 | date range, class, resolution status | reconciliations with discrepancy |
| 6 | `progress_overall` | Overall Cycle Count Progress | W2 PROGRESS-overall | section, plant | metrics.overall |
| 7 | `progress_weekly` | Weekly Cycle Count Progress | W2 PROGRESS-weekly | date range, class | metrics.weekly |
| 8 | `amc` | AMC Report | W1 AB + W2 E,O | analysis run, section | analysis results + latest counts |
| 9 | `abc` | ABC Analysis Report | W1 family sheets | analysis run, family | analysis results |
| 10 | `movement` | Inventory Movement Classification | W1 AA / CLASS | analysis run, class | analysis results |
| 11 | `schedule` | Cycle Count Schedule & Overdue | W2 K,L filter | as-of date, horizon, status | scheduling engine |
| 12 | `accuracy_trend` | Accuracy & Variance Trends | PROGRESS-weekly charts | date range, granularity | reconciliations |
| 13 | `data_quality` | Data Quality & Unmatched Inventory | (none; implicit #N/A, "not found") | kind, status | dq_exception |
| 14 | `sync_history` | Odoo Synchronisation History | (none) | date range, status | sync_run |
| 15 | `audit_trail` | Inventory Audit Trail | (none) | date range, user, entity | audit_log |
| 16 | `custom` | Custom Filtered Inventory Report | ad-hoc Excel filtering | allowed fields, filters, sort, group | masterlist dataset |
