# 09 — Data Quality and Exception Register

Figures come from [`tools/xl_data_checks.py`](../../tools/xl_data_checks.py), run on the reference files dated 10.13.26. The OICAS `dq_exception.kind` that detects each issue at runtime is shown where one applies.

| ID | Issue | Where | Size | Impact | OICAS handling (kind) |
|---|---|---|---|---|---|
| DQ-01 | Family total range truncated `SUM(P3:P678)` vs 907 rows | W1 RM!P1 | cum % ends at 123.6 % | RM ABC classes wrong | full total (UD-01) |
| DQ-02 | Family sheet not sorted by total demand before cumulating | W1 RM (411 inversions), List excluded (21), T&D (1), SF Wood (1) | 618 RM items, 199 List-excluded items change class under Pareto order | ABC/action/interval wrong for those items | ranked engine (UD-01); comparison report shows the legacy vs recalculated class |
| DQ-03 | Item code in more than one family sheet | W1 | 159 codes (CONSOLIDATED 6,362 rows / 6,180 unique) | double-counted in #items | `duplicate_code_family` |
| DQ-04 | Duplicate rows in Masterlist | W2 Master | 6,268 rows / 6,086 unique (182 dupes) | PROGRESS #items inflated by 182 | item.code unique; legacy import reports dupes |
| DQ-05 | Counted codes not in Masterlist (incl. case variants e.g. `13t01-001`) | W3 LIST vs W2 Master | 102 codes; U = "-ER" on 157 lines | counts invisible on dashboard | `unknown_item_code` |
| DQ-06 | Masterlist classification differs from CONSOLIDATED; 94 CONSOLIDATED items absent from Master | W2 vs W1 | 4 diffs, 94 missing | stale copy | no copy step; single analysis source |
| DQ-07 | Uncounted items show ACTUAL COUNT 0, Odoo 0, discrepancy 0, stock-in-months 0 | W2 M:S, O | 5,024 uncounted rows | zeros read as confirmed | NULL semantics (BR-22) |
| DQ-08 | Missing Odoo balance returns 0 (`XLOOKUP(...,0)`) | W2 P,Q | n/a | false discrepancy | `odoo_balance_missing` (BR-23) |
| DQ-09 | Negative Odoo on-hand | W3 ODOO inv | 19 WH, 37 PROD rows | discrepancy against a negative stock | `negative_odoo_qty` |
| DQ-10 | Odoo download overwritten / partial; LIST P not traceable to a snapshot | W3 | 923 of 1,370 traceable | reports not reproducible | persistent `inventory_snapshot` |
| DQ-11 | Duplicate (date, code) count lines | W3 LIST | 14 pairs | summed by SUMIFS, Odoo taken from first line | entries summed (BR-15); `duplicate_count_line` on import |
| DQ-12 | TOTAL COUNT (PROD) has no formula and is never filled; PROD-1..4 empty | W3 LIST E, L:O | 0 PROD entries | production discrepancy always = −Odoo pre-prod | PROD entries supported; bucket marked "not counted" when none |
| DQ-13 | UoM not found for item | W2 J | 41 items | – | `missing_uom` |
| DQ-14 | Inconsistent UoM spellings (Piece/PC/UN/Unit, M/Meter/m, LITERS/Liters/LT, SHT/SHEET) | W2 DATA G | ~30 variants | – | `uom_alias` mapping (display only; no conversion) |
| DQ-15 | Plant location 0 / blank | W2 G | 1,220 items | location-based scheduling impossible | `missing_plant_location` |
| DQ-16 | Material section 0 / blank | W2 F | 8 items | family unknown | `missing_material_section` |
| DQ-17 | Broken formula `UNIQUE(#REF!)` | W2 DATA!A1 | 1 | none (unused) | n/a |
| DQ-18 | External link to a UNC path `\\172.16.0.4\…` | W2 → W3 | – | breaks when moved or offline | removed (single DB) |
| DQ-19 | Weekly progress values typed by hand; #DIV/0! for weeks without counts | W2 PROGRESS-weekly | 4 blocks | – | computed weekly metrics |
| DQ-20 | Product code duplicates in product master exports | W2 DATA F (6), W3 DATA C (21) | – | ambiguous UoM/description | `duplicate_product_code` (Odoo sync) |
| DQ-21 | Header label "TOTAL Sep-May" but formula sums Sep–Aug | W1 CONSOLIDATED P1 | – | misleading | report shows the period explicitly |
| DQ-22 | AMC uses only months with records, so a single big month gives a high AMC | W1 AB | business rule | stock-in-months understated | documented (UD-02) |
