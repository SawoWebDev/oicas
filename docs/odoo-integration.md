# Odoo Integration

OICAS is **read-only** toward Odoo. It never creates stock adjustments, moves or product changes. That restriction is enforced in code (`oicas/odoo/client.py`, `READ_ONLY_METHODS`) and covered by tests.

## What OICAS reads

| Purpose | Model | Domain | Fields |
|---|---|---|---|
| Locations | `stock.location` | `usage = internal` | complete_name, usage, company_id, warehouse_id, active |
| Items | `product.product` | active products | default_code, display_name, name, uom_id, active |
| On-hand stock | `stock.quant` | `location_id.usage = internal` | product_id, location_id, quantity, company_id |
| Demand (AMC/ABC) | `stock.move` | `raw_material_production_id != False`, `create_date` in period (company timezone), state ≠ cancel (setting) | product_id, product_uom_qty, create_date, state |
| Login | `res.users`, `ir.model.data` | the user's own record | login, name, email, share, active, groups → XML ids |

Demand uses the same basis as the legacy workbook's hidden `Sheet1`: *Components / Created on / Product Reference / Demand*. Months are bucketed in `APP_TIMEZONE` (default Asia/Manila; see UD-11).

## Location buckets

Odoo locations map to the two legacy columns **WAREHOUSE** (`Odoo WH`) and **PRODUCTION** (`Odoo Pre-prod`). An administrator assigns each internal location a bucket under *System Configuration → Odoo locations*. Unmapped locations are excluded from balances and listed in Data Quality. The raw per-location quantities are still stored (`snapshot_quant`), so they can be re-derived.

## Snapshots

Each successful inventory sync writes an immutable snapshot. When a count session is finalized, it's reconciled against the latest snapshot. If that snapshot is older than `odoo_stale_after_hours` (default 24), finalizing requires an explicit confirmation, and every page shows a stale-data banner. A failed sync leaves all existing data untouched (savepoint rollback), is logged in Synchronization History and raises a Data Quality exception.

In a complete Odoo snapshot, a product with no quant in a bucket has an Odoo balance of **0**. A code that isn't an Odoo product has **no** balance (`odoo_missing`).

## Connecting (ERP login, no API key)

1. In `.env` set `ODOO_MODE=live`, `ODOO_URL=https://erp.sawo.com` and `ODOO_DB=sawo`, then run `docker compose up -d`.
2. Log in to OICAS with your ERP login and password.
3. As a manager: *Synchronization History → Sync Odoo now*. The sync reads Odoo with **your** ERP login and access rights (Inventory / User or higher can read products, locations and quants; *Manufacturing / User* if MO moves are restricted). After a server restart, the button asks for your ERP password once.
4. Map the locations (*System Configuration → Odoo locations*), then sync again.
5. Optional checks from the command line, with the password prompted and never stored: `docker compose exec web python -m oicas.cli odoo-probe --login you@sawo.com`.

`erp.sawo.com` is only ever read: every call passes the read-method whitelist before anything reaches the network.

## Users and roles

End users log in with their usual ERP (Odoo) login and password. The default group → role mapping is editable under *System Configuration → Settings → auth group role map*:

| Odoo group | OICAS role |
|---|---|
| `base.group_system` | admin |
| `stock.group_stock_manager` | manager |
| `stock.group_stock_user` | counter |
| any other internal user | `auth_default_role` (viewer) |

If SAWO later switches Odoo to SSO (OAuth/SAML) without passwords, the login has to move to the same identity provider (UD-09).

## Verification status

* Tested against an in-memory Odoo fixture (`ODOO_MODE=fake`) that implements the same read-only contract.
* 2026-10-20: `https://erp.sawo.com` (database `sawo`) is reachable from the Docker host and reports **Odoo 17.0 Enterprise** (`server_version 17.0+e-20250901`).
* Pending: first live login and first live sync by a SAWO manager (both use the ERP login; no API key needed).
