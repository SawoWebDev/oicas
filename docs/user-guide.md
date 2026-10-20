# OICAS User Guide

> **In the app:** press **F1** (or the red **?** button, bottom right) on any page for help about that page. The **Help Center** (sidebar) has the full guide: workflow, data relationships, every module with examples, imports, Odoo loading, formulas, roles, glossary and FAQ.

Written for inventory counters, inventory controllers/managers and management viewers.

## Signing in
Open OICAS (e.g. `http://<server>:8086`) and log in with your **Odoo** login and password. OICAS doesn't keep your password; Odoo checks it. What you can do depends on your role:

| Role | Can |
|---|---|
| Viewer | See the dashboard, masterlist, analyses, reports and exports |
| Counter | + start count sessions, enter or upload counts, submit them |
| Manager | + finalize counts against Odoo, correct submitted counts, review discrepancies, plan counts, run and approve analyses, sync Odoo, edit item attributes, resolve data-quality issues, view the audit trail |
| Admin | + rule sets, settings, location mapping, users |

A yellow **Development fixture** banner means you're on a test system with simulated Odoo data. A red **stale** banner means the Odoo figures are older than the allowed age, so treat them as not current.

## Daily workflow (replaces the Excel copy/paste steps)

1. **Plan**: *Cycle Count Planning* lists every item with its last count, interval and next count (overdue first, Close Control before Regular and Infrequent review). Create a plan from all due/overdue items or from ticked items, and assign people.
2. **Count**: open the plan and either
   * download the **Count sheet (Excel)**, fill in WH-1…WH-4 / PROD-1…PROD-4 and upload it on *Physical Counting*, or
   * press **Start counting** and enter each figure (code, location, slot, quantity).
   Leave a location **blank** if you didn't count it. Enter **0** only when you counted and found nothing. Several entries for the same item and location on the same day are added together, as in the old COUNTED LIST.
3. **Submit**: after submission, entries can't be edited. A manager can **correct** an entry by giving a new quantity and a reason; the original stays in history.
4. **Finalize** (manager): OICAS compares physical against the latest Odoo snapshot per location. *Variance = physical − Odoo*.
5. **Review discrepancies**: *Odoo Reconciliation* → open an item → add a note, mark *investigating*, **request a recount** (adds it to the *Recount requests* plan) or **resolve** with an explanation. OICAS never changes Odoo; stock adjustments are still done in Odoo by the authorised person.
6. **Next cycle**: the next count date updates automatically (last count + interval).

## Importing data that isn't in Odoo (Data Import)
Some items aren't encoded in Odoo yet, or have no code. Managers bring them in under **Inventory → Data Import**. Each import has a **Template** button (an Excel file with a DATA sheet, a grey example row and a HOW TO sheet), a **Dry run** that checks everything without saving, and **Import**. If any row has an error, nothing is saved and every error is listed with its row number.

| Import | Use it for | Notes |
|---|---|---|
| 1. Items not in Odoo | New items, or items without a code | Blank code → temporary code `NC-00001`, `NC-00002`, … Also updates section / family / plant / remark / tracked for existing items (Odoo-owned description and UoM aren't changed). |
| 2. Book balances | The expected stock of items Odoo doesn't hold | When such an item is counted, it's compared with the latest book balance dated on or before the count date. The reconciliation shows "System balance from: imported book balance". Blank ≠ 0. |
| 3. Count lines | Many counts at once, in the COUNTED LIST layout | One session per date and counter, created as *submitted*; a manager finalizes. Optional BOOK WH / BOOK PROD columns store book balances at the same time. |
| 4. Demand | Consumption not recorded in Odoo | Same columns as the Odoo export. Then calculate a new analysis run (AMC Analysis). |

When an item is later encoded in Odoo, open it and use **Change item code**: all counts, reconciliations and demand move to the Odoo code, and the next sync links it. Until then it's listed under *Data Quality → not in odoo*.

## Masterlist
The legacy *Master* sheet, with the same columns: RM code, description, action, classification, AMC, material section, plant location, interval, UoM, counted date, next count, actual WH/PROD, stock in months, Odoo WH/Pre-prod, discrepancies and remark. Use the filters, click a column to sort, and click a code for the full item history (counts, corrections, reconciliations, demand by month and data-quality notes).

**“–” means unknown, not zero.** An item that hasn't been counted has no physical quantity, discrepancy or stock-in-months.

## Dashboard
Shows totals for active items, counted, remaining, accuracy, discrepancies and overdue counts; the *PROGRESS-overall* table per movement class; weekly progress; ABC distribution; progress by plant and by person; Odoo sync status; data-quality warnings. Click any figure to open the matching filtered list.

KPI definitions (unchanged from the Excel dashboard):
* Count completion = # counted ÷ # of items
* Inventory accuracy % (count based) = (# counted − # discrepancy) ÷ # counted
* Overall accuracy = (# counted − # discrepancy) ÷ # of items
* Discrepancy rate = # discrepancy ÷ # counted
* Weekly: weeks run Monday–Sunday; week # = Excel `WEEKNUM(date, 2)`; completion % = cumulative counted ÷ # of items.

## AMC / ABC / Movement
* **AMC** = average demand of the months with recorded demand in the period.
* **ABC (quantity)** within each family: items ranked by total demand; cumulative share < 80 % → A, ≥ 95 % → C, otherwise B.
* **ABC (frequency)** = months with demand ÷ months in the period: > 80 % → A, ≤ 50 % → C, otherwise B.
* The two letters form the **category** (e.g. AB), which sets action, classification and count interval (30/90/180 days). Items with no demand in any month are **Non Moving**.

Managers calculate a new analysis from Odoo demand (or an uploaded export) as a **draft**, review the list of changed items, then **approve** it. Only the approved run drives the masterlist and schedule.

## Reports
*Reports Center* holds 16 reports. Each one has filters and exports to **Excel** and **PDF**, which contain exactly what the screen shows, with the title, period, filters, data versions and generation time.
