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

## Setting up the service account

1. In Odoo, create an internal user, e.g. `oicas-sync`, with **read** access to Inventory (group *Inventory / User* is sufficient for products, locations, quants and moves; *Manufacturing / User* if moves are restricted).
2. As that user: *Preferences → Account Security → New API Key*. Put it in `.env` as `ODOO_SYNC_API_KEY`, with `ODOO_SYNC_LOGIN`, `ODOO_URL`, `ODOO_DB` and `ODOO_MODE=live`.
3. Run `docker compose exec web python -m oicas.cli odoo-probe`. It prints the server version, the internal locations and the number of readable products, and writes nothing.
4. Run a first sync (*Synchronization History → Sync Odoo now*), map the locations, then sync again.

## Users and roles

End users log in with their usual Odoo login and password (or a personal API key). The default group → role mapping is editable under *System Configuration → Settings → auth group role map*:

| Odoo group | OICAS role |
|---|---|
| `base.group_system` | admin |
| `stock.group_stock_manager` | manager |
| `stock.group_stock_user` | counter |
| any other internal user | `auth_default_role` (viewer) |

If the site uses Odoo SSO (OAuth/SAML) without passwords, users can log in with a personal API key instead. Replacing the login with the same identity provider is UD-09.

## Verification status

* Tested against an in-memory Odoo fixture (`ODOO_MODE=fake`) that implements the same read-only contract.
* 2026-10-20: `https://erp.sawo.com` (database `sawo`) is reachable from the Docker host and reports **Odoo 17.0 Enterprise** (`server_version 17.0+e-20250901`).
* Pending: first live login by a SAWO user, and the first live sync (needs the service-account API key).
