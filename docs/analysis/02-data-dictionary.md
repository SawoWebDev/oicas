# 02 — Worksheet and Column Data Dictionary

Origin legend: **IMP** = imported from Odoo, **MAN** = manually entered, **CALC** = formula, **COPY** = pasted from another workbook, **REF** = reference/lookup data.

## W1 `03_AMC Sep-Jul ABC Analysis.xlsx`

### `Sheet1` (hidden), raw demand export — IMP
| Col | Header | Type | Notes |
|---|---|---|---|
| A | Components/Created on | datetime | Creation timestamp of the MO component move (Odoo `stock.move.create_date`, shown in user TZ) |
| B | Components/Product/Reference | text | Odoo `default_code` = **item code** |
| C | Components/Product/Name | text | Product name |
| D | Components/Demand | number | Component demand qty (`stock.move.product_uom_qty`) in product UoM |

### `Demand`: pivot of Sheet1 by month — COPY
| Col | Header | Notes |
|---|---|---|
| A | Components/Product/Reference | Item code (unique, 7,442) |
| B | Components/Product/Name | |
| C…N | Aug, Sep, Oct, Nov, Dec, Jan, Feb, Mar, April, May, Jun, Jul | Monthly sum. Months with no demand hold `""` (empty text). There are no negatives |

### Family sheets (`RM`, `Box ABC Analysis`, …, `SF Wood ABC Analysis`). Row 1 = totals, row 2 = headers, data from row 3
| Col | Header | Origin | Meaning |
|---|---|---|---|
| A | # | CALC `SEQUENCE(B1,1)` | Row rank 1..n in **sheet order** |
| B | Code | MAN/COPY | Item code (B1 = `COUNTA` item count) |
| C | Description | MAN/COPY | |
| D…O | Sep … Aug | CALC VLOOKUP into Demand | Monthly demand, `""` when the month is absent |
| P | TOTAL | CALC `SUM(D:O)` | Total demand in the period (P1 = grand total) |
| Q | demand as a % of total demand | CALC `P/$P$1` | Share of family total |
| R | Frequency of Demand | CALC `COUNT(D:O)` | Number of months with a **numeric** value (an explicit 0 counts) |
| S | Cumulative % of items | CALC `A/$B$1` | Rank ÷ item count |
| T | Cumulative % of total demand | CALC running `T(prev)+Q` | |
| U | frequency % of item | CALC `R/11` | |
| V | Classification – demand quantity | CALC | A/B/C from T |
| W | Classification – demand frequency | CALC | A/B/C from U |
| X | Category | CALC `V&W` | AA…CC |
| Y | DECLARED INVENTORY TYPE | CALC VLOOKUP CLASS | MTS / MTO |
| Z | ACTION | CALC VLOOKUP CLASS | CLOSE CONTROL / REGULAR REVIEW / INFREQUENT REVIEW |
| AA | CLASSIFICATION | CALC | Fast/Medium/Slow Moving, or **Non Moving** when R = 0 |
| AB | AMC | CALC `IFERROR(AVERAGE(D:O),0)` | Average of numeric months |
| AC | Material Section | MAN | Family name (RAW MAT, BOX, Metal Stamping, …) |
| AD | Plant Location | MAN | 1, 2, 3, 4 or combinations ("1 & 3"); 0 = missing |

### `CONSOLIDATED`
Columns A:AD are the stacked family sheets (values). AE = `X&Y` (interval key, e.g. `ABMTS`), AF = `XLOOKUP(AE, CLASS!N, CLASS!G)` (interval days).

### `CLASS`: reference matrix (rows 5–14)
| Category (H) | Declared type (I) | Action (J) | Classification (K) | Short (L) | Days (G) |
|---|---|---|---|---|---|
| AA | MTS | CLOSE CONTROL | Fast Moving | FMI | 30 |
| AB | MTS | CLOSE CONTROL | Fast Moving | FMI | 30 |
| BA | MTS | CLOSE CONTROL | Fast Moving | FMI | 30 |
| BB | MTS | REGULAR REVIEW | Medium Moving | MMI | 90 |
| CA | MTS | REGULAR REVIEW | Medium Moving | MMI | 90 |
| AC | MTS | REGULAR REVIEW | Medium Moving | MMI | 90 |
| BC | MTO | INFREQUENT REVIEW | Slow Moving | SMI | 180 |
| CB | MTO | INFREQUENT REVIEW | Slow Moving | SMI | 180 |
| CC | MTO | INFREQUENT REVIEW | Slow Moving | SMI | 180 |
| (row 14) | – | – | – | NMI | "Normal Moving Inventory" (unused, no category) |

Plant locations (B17:B31): 1, 2, 3, 4, "1 & 2", "1 & 3", "1 & 4", "2 & 3", "2 & 4", "3 & 4", "1 & 2 & 3", "1 & 2 & 4", "1 & 3 & 4", "2 & 3 & 4", "1 & 2 & 3 & 4".

## W2 `Master`
| Col | Header | Origin | Source / formula |
|---|---|---|---|
| A | RM CODE | COPY | W1 CONSOLIDATED!B (A1 shows `Total: n`; validation list on A139) |
| B | DESCRIPTION | COPY | CONSOLIDATED!C |
| C | ACTION | COPY | CONSOLIDATED!Z |
| D | CLASSIFICATION | COPY | CONSOLIDATED!AA |
| E | AMC | COPY | CONSOLIDATED!AB |
| F | Material Section | COPY | CONSOLIDATED!AC |
| G | Plant Location | COPY | CONSOLIDATED!AD |
| H | INTERVAL (key, hidden) | COPY | CONSOLIDATED!AE |
| I | INTERVAL (days) | COPY | CONSOLIDATED!AF |
| J | Unit of Measure | CALC | `XLOOKUP(A, DATA!F, DATA!G, "- not found")` |
| K | COUNTED DATE | CALC (ext) | `MAXIFS(LIST!A, LIST!B, A)`: latest count date |
| L | NEXT COUNT | CALC | `K + I` |
| M | ACTUAL COUNT (WH) | CALC (ext) | `SUMIFS(LIST!D, LIST!A, K, LIST!B, A)`: sum of that day's WH totals |
| N | ACTUAL COUNT (PROD) | CALC (ext) | `SUMIFS(LIST!E, …)` |
| O | STOCK IN MONTHS | CALC | `IFERROR((M+N)/E, "")` |
| P | ODOO WH | CALC (ext) | `XLOOKUP(K&A, LIST!A&LIST!B, LIST!P, 0)`: first matching line |
| Q | ODOO PRE-PROD | CALC (ext) | same on LIST!Q |
| R | DISCREPANCY (WH) | CALC | `IFERROR(M − P, 0)` |
| S | DISCREPANCY (PROD) | CALC | `IFERROR(N − Q, 0)` |
| T | REMARK | CALC | `XLOOKUP(A, DATA!J, DATA!L, "-")` (JIT remark) |
| U | DISCREPANCY (FORMULA, hidden) | CALC | `IF(OR(R<>0, S<>0), 1, 0)` |
| AB | RM CODE LEGEND: JIT | MAN | legend label |

## W2 `DATA`
| Col | Header | Meaning |
|---|---|---|
| A | `UNIQUE(#REF!)` | broken array formula |
| B | LOCATION | WAREHOUSE / PRODUCTION for ~1,289 rows (purpose undocumented) |
| E | Display Name | `[code] name` from Odoo |
| F | code | item code |
| G | Unit of Measure | Odoo UoM name |
| J,K | ITEM CODE, ITEM DESCRIPTION | JIT list |
| L,M | REMARK 1, REMARK 2 | "JIT", provenance note |

## W3 `LIST`: count log
| Col | Header | Origin | Notes |
|---|---|---|---|
| A | DATE COUNTED | MAN | From the e-mailed count sheet |
| B | RM CODE | MAN | |
| C | Description | CALC | `XLOOKUP(B, DATA!C, DATA!D, 0)` |
| D | TOTAL COUNT (WH) | CALC | `SUM(H:K)` |
| E | TOTAL COUNT (PROD) | MAN (blank) | **No formula; never filled** (see DQ-12) |
| F | REMARKS | MAN | |
| G | COUNTED BY | MAN | Sender name |
| H…K | COUNT (WH-1…4) | MAN | Count entries per WH sub-location / round |
| L…O | COUNT (PROD-1…4) | MAN | Count entries for production / pre-production |
| P | Odoo WH | COPY | Pasted from `ODOO inv` for that date |
| Q | Odoo Pre-prod | COPY | |
| R | DISCREPANCY (WH) | COPY/CALC | Holds `D − P` (verified 2,209/2,209 rows) |
| S | DISCREPANCY (PROD) | COPY/CALC | `E − Q` |
| U | (no header) | COPY | Movement classification ("-ER" = code not in Master) |

## W3 `ODOO inv`
| Col | Header | Meaning |
|---|---|---|
| A | DL date | Date of the Odoo download (snapshot date) |
| B | Internal Reference | item code |
| C | Product Name | |
| D | WAREHOUSE | on-hand qty, warehouse locations |
| E | PRODUCTION | on-hand qty, pre-production location |
| F | REMARKS | e.g. "DOWNLOADED ON 09.23" |

## W3 `DATA`
Product (display), Product/Unit of Measure, RM CODE, DESCRIPTION. This is the Odoo product master export.
