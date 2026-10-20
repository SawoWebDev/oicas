# 08 — Business Rules Register

Status: **V** = verified against workbook data, **C** = corrected (pending approval, see 10-unresolved-decisions), **N** = new OICAS rule required by Task.md.

| ID | Rule | Status | Evidence | Engine |
|---|---|---|---|---|
| BR-01 | The analysis period is a list of consecutive calendar months. Legacy: Sep-2025…Jul-2026 (11) | V | Family D:N headers; `U = R/11` | `amc.Period` |
| BR-02 | Monthly demand = Σ MO component demand of the item with `Created on` in the month | V | Sheet1 → Sheet4 pivot | `importers.demand` / `odoo.sync.demand` |
| BR-03 | A month with no demand record is *missing*; an explicit 0 is a value | V | `""` vs 0; COUNT includes 0 | `amc.monthly_series` |
| BR-04 | Frequency = number of months with a value (incl. 0) | V (0 mism.) | F-05 | `abc.frequency` |
| BR-05 | AMC = mean of months with a value; 0 if none | V (0 mism.) | F-13 | `amc.amc` |
| BR-06 | ABC runs **per material-section family**, not across all items | V | 11 separate sheets with own totals | `abc.analyse_family` |
| BR-07 | Items are ranked by total demand descending before accumulating | V (9/11 sheets) / C (RM, List excluded) | inversions = 0 on 9 sheets | `abc.rank` |
| BR-08 | Family total = sum of all items' totals in the family | C | RM truncated range | `abc.analyse_family` |
| BR-09 | Qty class: A if cum < 80 %, C if cum ≥ 95 %, else B | V | F-08 | `abc.qty_class` |
| BR-10 | Freq class: A if freq% > 80 %, C if ≤ 50 %, else B | V | F-10 | `abc.freq_class` |
| BR-11 | Category = qty class & freq class; lookup in CLASS matrix gives declared type, action, classification, interval days | V | F-11/12/14 | `classification.classify` |
| BR-12 | Frequency 0 → classification "Non Moving" (action and interval stay from the category) | V | F-12 | `classification.classify` |
| BR-13 | Count interval days = CLASS!G by category (30/90/180) | V | F-14 | `classification` |
| BR-14 | Location total = sum of count entries (WH-1..4 / PROD-1..4) for the item, location and date | V | LIST D = SUM(H:K) | `reconciliation.aggregate` |
| BR-15 | The item's current physical qty = sum of the latest count date's entries (all lines of that date) | V | Master M/N SUMIFS | `reconciliation.latest` |
| BR-16 | Discrepancy = physical − Odoo, per location (WH vs WH, PROD vs Pre-prod) | V (2,209/2,209) | F-22 | `reconciliation.discrepancy` |
| BR-17 | An item has a discrepancy if either location's \|variance\| > tolerance (legacy tolerance 0) | V | F-23 | `reconciliation.has_discrepancy` |
| BR-18 | Odoo balance compared = snapshot of the count day | V | ODOO inv DL date = LIST date | `counting.finalize` |
| BR-19 | Next count = last count date + interval days | V | F-17 | `scheduling.next_due` |
| BR-20 | Overall KPIs per movement class (#items, #counted, #disc, completion, accuracy, overall accuracy, discrepancy rate) | V | F-24 | `metrics.overall` |
| BR-21 | Weekly KPIs: weeks Mon–Sun, label `WK#` + Excel WEEKNUM(type 2); completion = cumulative counted / #items | V | F-25 | `metrics.weekly` |
| BR-22 | An uncounted item has *no* physical quantity, stock-in-months or discrepancy (never 0) | N (corrects DQ-07) | Task.md §11 | `reconciliation` |
| BR-23 | A missing Odoo balance is NULL; the reconciliation status becomes `odoo_missing`, not a discrepancy vs 0 | N (corrects DQ-08) | Task.md §9 | `reconciliation` |
| BR-24 | Submitted count entries are immutable; corrections create a superseding entry with a reason | N | Task.md §11 | `counting.correct_entry` |
| BR-25 | Recount supersedes the earlier reconciliation for the item; history is kept | N | Task.md §10 | `counting.finalize` |
| BR-26 | Never-counted items are due immediately (due date = analysis approval date) until counted | N (UD-04) | Task.md §15 | `scheduling.next_due` |
| BR-27 | OICAS never writes to Odoo | N | Task.md §8 | `odoo.client` whitelist |
| BR-28 | Snapshot older than `odoo.stale_after_hours` (default 24) is flagged stale everywhere it's shown | N | Task.md §8 | `sync.staleness` |
| BR-29 | Stock in months = (phys WH + phys PROD) / AMC, NULL if not counted or AMC ≤ 0 | V + N | F-20 | `amc.stock_in_months` |
