"""Workbook uploads are numbered per module (AMC Import #1, #2 …; Physical Counting #1, #2 …), and stored uploads are
read again so they show dates in Excel's own format and the filter buttons of empty filter columns.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-16
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("amc_import", sa.Column("seq", sa.Integer(), nullable=True))
    conn = op.get_bind()
    n: dict[str, int] = {}
    for iid, kind in conn.execute(sa.text("SELECT id, kind FROM amc_import ORDER BY id")).fetchall():
        n[kind] = n.get(kind, 0) + 1
        conn.execute(sa.text("UPDATE amc_import SET seq = :s WHERE id = :i"), {"s": n[kind], "i": iid})

    from oicas.services.amc_import import parse_workbook
    for iid, content in conn.execute(sa.text("SELECT id, content FROM amc_import")).fetchall():
        for pos, s in enumerate(parse_workbook(bytes(content))):
            conn.execute(
                sa.text("UPDATE amc_import_sheet SET rows = :rows, merges = :merges, n_rows = :nr, n_cols = :nc, "
                        "header_row = :hr, layout = :layout, style_grid = :grid, style_table = :tbl "
                        "WHERE import_id = :i AND position = :p"),
                {"rows": json.dumps(s["rows"]), "merges": json.dumps(s["merges"]), "nr": s["n_rows"], "nc": s["n_cols"],
                 "hr": s["header_row"], "layout": json.dumps(s["layout"]), "grid": json.dumps(s["style_grid"]),
                 "tbl": json.dumps(s["style_table"]), "i": iid, "p": pos})


def downgrade() -> None:
    with op.batch_alter_table("amc_import") as b:
        b.drop_column("seq")
