# 01 — Excel Workbook Inventory

Source files are in [`docs/reference/`](../reference/). I inspected them with `openpyxl` (formulas and cached values), plus raw XML for external links, array formulas and embedded images. The scripts are reproducible:

| Script | Purpose |
|---|---|
| [`tools/xl_survey.py`](../../tools/xl_survey.py) | Sheets, visibility, dimensions, merged cells, validations, conditional formats, freeze panes, first rows, formula patterns per column |
| [`tools/xl_deep.py`](../../tools/xl_deep.py) | Array formulas, CLASS lookup table, external-link targets, automation-flow contents, embedded images |
| [`tools/xl_data_checks.py`](../../tools/xl_data_checks.py) | Data-level parity: sort order, recomputation of ABC/AMC/frequency, duplicates, Odoo-snapshot matching |

Run inside the analysis container: `docker run --rm -v "$PWD:/w" -w /w oicas-xl python tools/<script>.py`.

---

## W1 — `03_AMC Sep-Jul  ABC Analysis.xlsx` (10.3 MB)

Purpose: demand-based **ABC analysis**, **AMC** and **movement classification** per item family; the source of Action / Classification / AMC / Material Section / Plant Location / Interval for the Masterlist.

| # | Sheet | State | Used range | Role |
|---|---|---|---|---|
| 1 | `Sheet1` | **hidden** | A1:D83499 | Raw Odoo export of MO component demand: `Components/Created on`, `Components/Product/Reference`, `Components/Product/Name`, `Components/Demand`. **Imported** |
| 2 | `Sheet4` | **hidden** | A3:P5675 | Pivot of Sheet1: Sum of Demand by product × year/quarter/month (Aug-2025 … Jul-2026). **Derived (pivot)** |
| 3 | `CONSOLIDATED` | visible | A1:AF15230 | `VSTACK(FILTER(...))` of all 11 family sheets (6,362 rows) + interval key (AE) and interval days (AF). **Calculated** |
| 4 | `CLASS` | visible | B1:N1000 | Lookup matrix: Category (AA…CC) → Declared inventory type, Action, Classification, interval days; plant-location list. **Reference** |
| 5 | `Demand` | visible | A1:R7445 | Pivot values pasted: code, name, monthly demand Aug…Jul (7,442 items; blanks are `""` text). **Imported (paste)** |
| 6 | `RM` | visible | A1:AD999 | Family sheet: Raw Materials (907 items). 905 rows hidden by filter |
| 7 | `Box ABC Analysis` | visible | A1:AD1000 | Family: BOX (685) |
| 8 | `MS ABC Analysis` | visible | A1:AN1710 | Family: Metal Stamping (1,708). 1,707 rows hidden by filter |
| 9 | `PA ABC Analysis` | visible | A1:AD1000 | Family: Pre-Assy (783) |
| 10 | `Stone ABC Analysis` | visible | A1:AD1000 | Family: Stone (74) |
| 11 | `T&D ABC Analysis` | visible | A1:AD1000 | Family: T&D (99) |
| 12 | `PIM ABC Analysis` | visible | A1:AD1000 | Family: PIM (66) |
| 13 | `CU ABC Analysis` | visible | A1:AD1000 | Family: Control Unit (23) |
| 14 | `WS ABC Analysis` | visible | A1:AD1000 | Family: Wood (367) |
| 15 | `List excluded` | visible | A1:AD999 | Mixed items (Innova, Consumables, Expensive WH…) (224) |
| 16 | `SF Wood ABC Analysis` | visible | A1:AD1428 | Family: SF Wood (1,426) |
| 17 | `Sheet1 (2)` | **hidden** | A1:D83382 | Older copy of the raw demand export |

- Defined names: none. Tables: none. External links: none. Data validations: none.
- Conditional formats: A/B/C colouring on V:W (green A, yellow B, red C); `AD = 0` highlight on CONSOLIDATED (missing plant location).
- Reporting period: **Sep-2025 → Jul-2026 (11 months)**. Column O "Aug" is present but only 1 row has a value. The frequency divisor is hard-coded `/11`. The CONSOLIDATED header "TOTAL Sep-May" is a stale label: the formula sums D:O (Sep–Aug).

## W2 — `10.13.26 INVENTORY MASTERLIST & CYCLE COUNT TRACKER.xlsx` (3.1 MB)

Purpose: **Inventory masterlist**, latest count results, discrepancy versus Odoo, and progress dashboards.
External link `[1]` = `\\172.16.0.4\Warehouse\...\COUNTED LIST\COUNTED LIST.xlsx`, sheets `LIST`, `ODOO inv`, `DATA`.

| # | Sheet | State | Used range | Role |
|---|---|---|---|---|
| 1 | `PROGRESS-overall` | visible | A1:Z22 | KPI table by movement class + 1 combo chart. **Calculated** |
| 2 | `PROGRESS-weekly` | visible | A1:BM35 | Four weekly blocks (Fast A:G, Medium U:AA, Slow AN:AT, Non BG:BM) + 4 charts. **Manual counts + formulas** |
| 3 | `Master` | visible | A1:AB10000 | 6,268 item rows (6,086 unique codes). Hidden columns H (interval key) and U (discrepancy flag) |
| 4 | `DATA` | visible | A1:M33270 | F:G Odoo product code → UoM; J:M JIT item list with remarks; B "LOCATION" partially filled; A1 `UNIQUE(#REF!)` (broken) |

- Cell comments (author Jovielyn): A1 "Copy at AMC from B to C"; C1 "Copy at AMC from Z to AF". These document the manual copy step from W1 CONSOLIDATED.
- Conditional formats: Action colour (CLOSE / REGULAR / INFREQUENT), Classification colour, `=0` highlights on M:U, `<0` on P:U, "not found" on P/Q/W.

## W3 — `COUNTED LIST.xlsx` (2.3 MB)

Purpose: the **physical count log** (every count line) and the **Odoo stock snapshot** used for comparison.

| # | Sheet | State | Used range | Role |
|---|---|---|---|---|
| 1 | `LIST` | visible | A1:U5000 | 2,840 count lines from 2026-08-31 to 2026-10-13. Up to 4 WH and 4 PROD count entries per line. Odoo WH / Pre-prod balances, discrepancies, class (U) |
| 2 | `ODOO inv` | visible | A1:I17913 | Odoo stock download: DL date, Internal Reference, Product Name, WAREHOUSE qty, PRODUCTION qty, remarks. 850 populated rows across 11 download dates |
| 3 | `DATA` | visible | A1:D34882 | Odoo product list: display name, UoM, code, description (34,881 rows) |

## W4 — `automation flow 2.xlsx` (0.4 MB)

Purpose: the **business owner's specification** of the target automation. It has no live formulas except `=G&H` key builders.

| # | Sheet | Content |
|---|---|---|
| 1 | `MAIN PAGE` | Field-by-field description of the Masterlist; overall dashboard KPI definitions; weekly dashboard definitions. 4 screenshots (Masterlist left/right, PROGRESS-overall, PROGRESS-weekly Fast) |
| 2 | `COUNTED LIST` | Field definitions of the count log. 2 screenshots |
| 3 | `AMC` | Field definitions of the ABC/AMC output, copy of the CLASS matrix and plant-location list. 2 screenshots |

Its definitions are quoted verbatim in [03-formula-register.md](03-formula-register.md) and [08-business-rules.md](08-business-rules.md).
