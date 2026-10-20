# 04 — Cross-Workbook Dependency Map

```mermaid
flowchart LR
  subgraph ODOO[Odoo ERP]
    O1[MO component moves<br/>stock.move: create_date, product, product_uom_qty]
    O2[Stock on hand<br/>stock.quant by location]
    O3[Product master<br/>product.product: default_code, name, uom]
  end

  subgraph W1[03_AMC Sep-Jul ABC Analysis.xlsx]
    S1[Sheet1 raw export] --> S4[Sheet4 pivot by month]
    S4 -. paste values .-> DEM[Demand]
    DEM --> FAM[11 family sheets<br/>D:O VLOOKUP → P..AB]
    CLASS[CLASS matrix] --> FAM
    FAM --> CONS[CONSOLIDATED<br/>VSTACK + AE/AF interval]
    CLASS --> CONS
  end

  subgraph W3[COUNTED LIST.xlsx]
    EMAIL[[E-mailed count sheets<br/>from inventory in-charge]] -. typed .-> LIST
    ODINV[ODOO inv download] -. paste per date .-> LIST
    CDATA[DATA product list] --> LIST
    LIST[LIST<br/>D=SUM(H:K), R=D-P]
  end

  subgraph W2[INVENTORY MASTERLIST & CYCLE COUNT TRACKER.xlsx]
    CONS -. manual copy B:C, Z:AF .-> MASTER[Master A:I]
    MDATA[DATA code→UoM, JIT list] --> MASTER
    LIST == external link [1] ==> MASTER
    MASTER --> PO[PROGRESS-overall]
    PO --> PW[PROGRESS-weekly]
    LIST -. manual weekly tally .-> PW
  end

  O1 --> S1
  O2 --> ODINV
  O3 --> CDATA
  O3 --> MDATA
```

## Field-level lineage (final report fields)

| Final field (W2 Master / dashboards) | Upstream chain |
|---|---|
| Classification (D) | Odoo MO moves → Sheet1 → Sheet4 → Demand → family D:O → R (frequency), P→Q→T (cumulative) → V,W → X → CLASS lookup → AA → CONSOLIDATED → *copy* → Master D |
| Action (C) | … X → CLASS → Z → copy |
| Interval days (I) | X & Y → CLASS!N → G → CONSOLIDATED AF → copy |
| AMC (E) | Demand → D:O → AVERAGE → AB → copy |
| UoM (J) | Odoo product export → W2 DATA F:G |
| Counted date (K) | e-mail → LIST A,B → MAXIFS |
| Next count (L) | K + I |
| Actual WH/PROD (M,N) | LIST H:K → D (and E) → SUMIFS on (K, code) |
| Odoo WH/PROD (P,Q) | Odoo stock download → ODOO inv → paste into LIST P,Q → XLOOKUP(K&A) |
| Discrepancy (R,S) | M−P, N−Q |
| Discrepancy flag (U) | R,S |
| Stock in months (O) | (M+N)/E |
| PROGRESS-overall | Master D, K, U |
| PROGRESS-weekly | typed weekly totals + PROGRESS-overall #items |

## Calculation sequence (as OICAS runs it)
1. Sync Odoo products/UoM, then sync stock quants into a snapshot.
2. Import or sync demand history (monthly buckets).
3. Analysis run: per family, total → rank → share → cumulative → V/W → category → CLASS lookup → classification/action/interval → AMC.
4. Masterlist view = item + current analysis result + latest finalized count + its Odoo snapshot line.
5. Reconciliation: discrepancy per location → flag.
6. Metrics: overall and weekly progress from reconciliation results.
7. Schedule: next due = last finalized count date + interval.
