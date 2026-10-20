# 03 — Formula and Calculation Register

Each entry lists: source → original formula → inputs → business meaning → missing/invalid handling → rounding → validation → **decision** (Preserve / Correct / Confirm). "Engine" names the OICAS function that owns the rule. All engine code lives in [`backend/oicas/engine/`](../../backend/oicas/engine/).

Rounding: Excel works in IEEE double with no rounding inside formulas; display formats round only for presentation. OICAS stores quantities as `NUMERIC(18,5)` (Odoo `Product Unit of Measure` precision is 5 dp in the data, e.g. `94.99999`) and percentages as unrounded floats, rounding only at presentation and export time.

---

## F-01 Monthly demand
- **Source**: W1 family sheets D:O. `=IFERROR(VLOOKUP($B3,Demand!$A$3:$M$10000,4..13,0),"")`, N uses `$A$3:$N$10000,14`.
- **Inputs**: Demand pivot (code × month), itself the sum of Sheet1 `Components/Demand` by month of `Created on`.
- **Meaning**: Quantity of the item consumed by manufacturing orders in the month.
- **Missing**: Item absent from Demand, or month cell `""`, gives `""`, which is **not** a number. An explicit `0` stays numeric.
- **Note**: Column O (Aug) has no formula; only 1 row has a value. The period is effectively Sep–Jul.
- **Decision**: Preserve. Engine `amc.monthly_series()` keeps `None` (no record) distinct from `0`.

## F-02 Total demand
`P = SUM(D:O)`. Treats `""` as 0. **Preserve** (`abc.total_demand`).

## F-03 Family total (denominator)
`P1 = SUM(P3:P678)` (RM) / `SUM(P3:P…)` per sheet.
- **Defect (DQ-01)**: In `RM` the range stops at row 678, but the data runs to row 909. The denominator is 3,098,777.51 while the true total is 3,830,552.06, so the cumulative % reaches **123.6 %**.
- **Decision**: **Correct (pending approval, UD-01)**. OICAS uses the full family total. Parity tests replay the truncated total to prove formula equivalence.

## F-04 Demand share
`Q = P / $P$1`. Division by zero gives #DIV/0!; OICAS returns 0 share when the family total is 0. **Preserve**.

## F-05 Frequency of demand
`R = COUNT(D:O)`: months holding a numeric value, **including explicit zeros**. Verified 0 mismatches across 6,362 rows. **Preserve** (`abc.frequency`).

## F-06 Cumulative % of items
`S = A / $B$1`, where A = `SEQUENCE(B1)` = row position. Informational only. **Preserve** (computed after ranking).

## F-07 Cumulative % of total demand
`T3 = Q3`, `Tn = T(n-1) + Qn`, accumulated in **sheet row order**.
- 9 of 11 family sheets are sorted by P descending, so this is a Pareto cumulative.
- **Defect (DQ-02)**: `RM` (411 order inversions) and `List excluded` (21) are **not** sorted. Their cumulative runs in alphabetical/description order. Cached values reproduce exactly only under that order (verified).
- **Decision**: **Correct (UD-01)**. OICAS ranks by total demand descending, ties broken by item code ascending, then accumulates. The `legacy_sheet_order` mode is kept for parity replay only.

## F-08 ABC by demand quantity
`V = IF(T<80%,"A",IF(T>=95%,"C","B"))`.
- A: cumulative < 80 %; B: 80 % ≤ cum < 95 %; C: cum ≥ 95 %. Comparison is on the cumulative **including** the item itself.
- **Decision**: **Preserve**; thresholds are configurable (`abc.qty_a_below=0.80`, `abc.qty_c_from=0.95`), versioned with an effective date.

## F-09 Frequency % of item
`U = R / 11`. The divisor 11 is hard-coded as the number of months in the period.
**Decision**: Preserve the semantics as "number of months in the analysis period", derived from the selected period (11 for Sep-2025..Jul-2026). See UD-03.

## F-10 ABC by demand frequency
`W = IF(U>80%,"A",IF(U<=50%,"C","B"))`. A: > 80 %; C: ≤ 50 %; B otherwise. Verified 0 mismatches. **Preserve**, configurable (`abc.freq_a_above=0.80`, `abc.freq_c_upto=0.50`).

## F-11 Category
`X = CONCATENATE(V, W)`, giving one of 9 categories (AA…CC). **Preserve**.

## F-12 Declared inventory type / Action / Classification
`Y = VLOOKUP(X, CLASS!H5:L13, 2)`, `Z = …,3`, `AA = IF(R=0,"Non Moving",VLOOKUP(X,…,4))`.
- **Non Moving overrides** whenever frequency = 0, regardless of category. Action/declared type still come from the category: a non-moving item with category AC keeps "REGULAR REVIEW" and a 90-day interval.
- **Decision**: **Preserve** (`classification.classify`). The CLASS matrix is seeded as versioned configuration.

## F-13 AMC (Average Monthly Consumption)
`AB = IFERROR(AVERAGE(D:O),0)`: the average of **months with a numeric value only**. Verified 0 mismatches.
- Example: 8RM04-341-1 total 745.70 over 6 recorded months gives AMC 124.28 (not 745.70 / 11 = 67.79).
- Items with no recorded months get AMC 0 (shown as Non Moving).
- **Decision**: **Preserve as the legacy rule; confirm (UD-02)**. An alternative "total ÷ period months" is available as a configurable method but is not the default.

## F-14 Interval key and interval days
`AE = X & Y`, `AF = XLOOKUP(AE, CLASS!N5:N14, CLASS!G5:G14, "- Not Found")`: 30 / 90 / 180 days by category. **Preserve** (`classification.interval_days`).

## F-15 Unit of measure lookup (Master J)
`XLOOKUP(A, DATA!F, DATA!G, "- not found")`. 41 items are not found. **Preserve** semantics; OICAS reads the UoM from Odoo `product.product.uom_id` and logs a DQ exception when it's missing.

## F-16 Counted date (Master K)
`LET(d, MAXIFS(LIST!A, LIST!B, A), IF(OR(A="", d=0), "", d))`: the latest count date for the item. Verified (0 mismatches). **Preserve** (`reconciliation.latest_count_date`). Only **finalized** count sessions qualify in OICAS.

## F-17 Next count (Master L)
`IFERROR(K + I, "")`: last count date + interval days. Never-counted items get blank. **Preserve**; the never-counted rule is UD-04 (`scheduling.next_due`).

## F-18 Actual count WH / PROD (Master M, N)
`SUMIFS(LIST!D|E, LIST!A, K, LIST!B, A)`: the sum of all count lines for the item **on the latest count date**. Earlier dates are ignored. Multiple same-day lines are **added** (14 duplicate date+code pairs exist).
- Uncounted item: K = "" gives SUMIFS = **0**, which displays as a confirmed zero (DQ-07).
- **Decision**: Preserve the aggregation (sum of entries of the latest count date per location). **Correct** the uncounted case: OICAS returns `NULL` (not counted), never 0.

## F-19 LIST total count WH (LIST D)
`SUM(H:K)`: WH-1..WH-4 entries summed. PROD total (E) has no formula (DQ-12).
**Decision**: Preserve: location total = sum of that location's entries. OICAS stores each entry as its own row (`count_entry`).

## F-20 Stock in months (Master O)
`IFERROR((M+N)/E, "")`: physical qty ÷ AMC. Blank when AMC = 0.
- Uncounted items with AMC > 0 show **0** (DQ-07).
- **Decision**: Preserve the formula; return `NULL` when not counted or AMC is 0 or missing.

## F-21 Odoo balances (Master P, Q)
`XLOOKUP(K&A, LIST!A&LIST!B, LIST!P|Q, 0)`: Odoo WH / Pre-prod balance stored on the **first** LIST line of the latest count date. LIST P/Q are pasted from the `ODOO inv` download of that day.
- Not found gives **0** (DQ-08: missing Odoo balance shown as zero).
- **Decision**: Preserve the snapshot semantics. OICAS links each count session to the Odoo snapshot taken at or before finalisation, and stores `NULL` when no balance exists.

## F-22 Discrepancy WH / PROD (Master R, S; LIST R, S)
`IFERROR(M − P, 0)`, `IFERROR(N − Q, 0)`: **signed physical − Odoo** (sign verified on 2,209/2,209 LIST rows).
- No tolerance: any non-zero difference (including 1e-5 float noise) is a discrepancy.
- **Decision**: **Preserve** the sign. Tolerance is configurable, default 0 = legacy (UD-06).

## F-23 Discrepancy flag (Master U)
`IF(OR(R<>0, S<>0), 1, 0)`. **Preserve** (`reconciliation.has_discrepancy`). Applies to counted items only.

## F-24 PROGRESS-overall
For each class C ∈ {Fast, Medium, Slow, Non Moving}:
| KPI | Formula | Engine |
|---|---|---|
| # of items | `COUNTIF(Master!D, C)` (counts duplicate rows) | `metrics.overall` |
| # counted | `SUMPRODUCT((Master!D=C)*(Master!K<>""))` | items with ≥1 finalized count |
| # of discrepancy | `SUMIF(Master!D, C, Master!U)` | counted items with discrepancy on their latest count |
| Count completion | `#counted / #items` | |
| Inventory Accuracy % (count based) | `(#counted − #disc) / #counted` | |
| OVERALL ACCURACY | `(#counted − #disc) / #items` | |
| Discrepancy Rate % | `#disc / #counted` | |
Verified values (10.13.26): Fast 850/500/493; Medium 887/353/296; Slow 3076/196/169; Non 1455/195/92.
- "# counted" is **all-time** (any count date), not per cycle (UD-05).
- **Decision**: Preserve. Zero denominators give `NULL` (Excel #DIV/0!).

## F-25 PROGRESS-weekly (per class block)
| Column | Formula |
|---|---|
| DATE | week-ending date (Sunday), typed |
| WEEK # | `"WK#"&WEEKNUM(date, 2)`: Excel week number, weeks start **Monday**, week 1 contains Jan 1 |
| TOTAL COUNTED | **typed manually**: items of the class counted within Mon..Sun |
| DISCREPANCY | **typed manually** |
| ACCURATE ITEMS | `C − D` |
| ACCURACY % | `E / C` (#DIV/0! on empty weeks) |
| Completion % | `SUM($C$2:Cn) / 'PROGRESS-overall'!#items` (cumulative) |
- **Decision**: Preserve the formulas. OICAS calculates TOTAL COUNTED and DISCREPANCY from count records instead of typing them. Weeks with 0 counted show accuracy `NULL`.
- Note: cumulative completion can exceed 100 % if items are re-counted in later weeks, because the counts are summed, not de-duplicated (UD-05).

## F-26 Masterlist / CONSOLIDATED row counters
`="Total: "&COUNTIF(A2:A10000,"<>")`, `="total "&COUNTA(B2:B10000)`. Presentation only.
