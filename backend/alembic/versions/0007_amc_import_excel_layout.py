"""AMC Import shows sheets exactly as Excel draws them: layout, cell styles (fonts, fills, borders, conditional
formatting), column widths, row heights, hidden rows, frozen panes. Existing sessions are re-read from the stored file.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-13
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("amc_import_sheet", sa.Column("layout", sa.JSON(), nullable=True))
    op.add_column("amc_import_sheet", sa.Column("style_grid", sa.JSON(), nullable=True))
    op.add_column("amc_import_sheet", sa.Column("style_table", sa.JSON(), nullable=True))
    from oicas.services.amc_import import parse_workbook
    conn = op.get_bind()
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
    with op.batch_alter_table("amc_import_sheet") as b:
        b.drop_column("style_table")
        b.drop_column("style_grid")
        b.drop_column("layout")
