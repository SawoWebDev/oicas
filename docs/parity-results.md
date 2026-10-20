# Excel Parity Results

Last run: 2026-10-20 · `python -m pytest -q` → **65 passed** (14 formula-parity, 3 migration-parity, 21 service, 27 web).

## Formula parity: `tests/parity/test_excel_parity.py`
The engine is replayed against the cached values in the reference workbooks.

| Check | Rows | Result |
|---|---|---|
| ABC/AMC per family sheet (F-02…F-13): total, share, frequency, cumulative %, frequency %, qty/freq class, category, AMC | 6,362 | **100 % identical** (cumulative to 1e-12), replaying sheet order and each sheet's own `P1` |
| Pareto engine on correctly sorted sheets | 9 sheets | identical except items **tied** on total demand at a class boundary (tie order is arbitrary in Excel; OICAS orders by code) |
| Documented defects exist (DQ-01 truncated RM total → cumulative 123.6 %; DQ-02 unsorted RM / List excluded) | – | confirmed |
| CLASS lookup: declared type, action, classification, interval key and days (F-12, F-14) | 6,362 | 100 % |
| Masterlist latest count date, WH/PROD sums, Odoo balances, discrepancies, flag, next count, stock in months (F-16…F-23) | 1,244 counted items | 100 % |
| COUNTED LIST discrepancy sign `R = D − P` | 2,209 | 100 % |
| PROGRESS-overall (all 7 KPIs × 4 classes) | 28 values | 100 % |
| Weekly labels `WEEKNUM(date, 2)` and week-end dates | 4 weeks + edge cases | 100 % |

## Migration parity: `tests/parity/test_legacy_migration.py`
The three workbooks are migrated into an empty database, and the resulting Masterlist is compared with W2 `Master` item by item (unique codes), using the legacy replay rule set (uncounted location = 0, missing Odoo = 0).

* 6,086 unique items. All classifications, actions, intervals, counted dates, counted/not-counted flags and discrepancy flags match, apart from **34 explained differences**:
  * codes duplicated in the Masterlist (DQ-04): Excel keeps one row per family copy;
  * **13 count lines without any quantity** (DQ-23): Excel treats them as a count of 0; OICAS doesn't invent a zero;
  * **29 stale Masterlist copies** (DQ-06): the Masterlist's action/classification matches no CONSOLIDATED row for the code.
* PROGRESS-overall per class matches Excel exactly once those documented items are excluded.

## Effect of the default rules (BR-22 / BR-23)
Under the default rule set, an uncounted location or a missing Odoo balance is **not** treated as 0. For the 10.13.26 data this changes the number of items flagged with a discrepancy:

| Class | Legacy rules | OICAS default |
|---|---|---|
| Fast Moving | 482 | 353 |
| Medium Moving | 284 | 207 |
| Slow Moving | 162 | 76 |
| Non Moving | 90 | 63 |
| **Total** | **1,018** | **699** |

In 319 cases, the legacy "discrepancy" came only from comparing an uncounted production location, or a blank Odoo value, against zero. Which rule is official is decision **UD-14**. Both are available as rule-set versions.
