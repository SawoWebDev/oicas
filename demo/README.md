# Demo database

`oicas_demo.sql.gz` is a `pg_dump` of the **secondary (demo) database** `oicas_demo`, used when `ODOO_MODE=fake`.
It contains the legacy workbook history from `docs/reference/` (6,188 items, 2,833 count entries, 2,815 reconciliations,
3 analysis runs) plus simulated Odoo syncs, at schema revision `0002`. Login sessions were left out.

Demo logins (fake mode only): `admin`, `manager`, `counter`, `viewer` — password `demo`.

## Load it

With `ODOO_MODE=fake` in `.env` and the stack built once (`docker compose up -d --build`):

```bash
docker compose stop web worker
docker compose exec -T db dropdb -U oicas --if-exists oicas_demo
docker compose exec -T db createdb -U oicas oicas_demo
gunzip -c demo/oicas_demo.sql.gz | docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U oicas -d oicas_demo
docker compose up -d                         # web applies any newer migrations on start
```

This replaces the demo database only; the primary database `oicas` is not touched.

## Refresh it

```bash
docker compose exec -T db pg_dump -U oicas -d oicas_demo --no-owner --no-privileges \
  --exclude-table-data=auth_session | gzip -9 > demo/oicas_demo.sql.gz
```

Test and demo data always live in the **secondary** database `oicas_demo`. The **primary** database `oicas`
is for live Odoo data only: never load this dump into it and never dump it into this folder.
