"""AMC Import looks like Excel: amc_import.active_sheet (the tab the workbook opens on) and
amc_import_sheet.tab_color (sheet-tab colours)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("amc_import", sa.Column("active_sheet", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("amc_import_sheet", sa.Column("tab_color", sa.String(length=7), nullable=True))
    # fill both in for sessions uploaded before these columns existed
    from oicas.services.amc_import import active_position, tab_colors
    conn = op.get_bind()
    for iid, content in conn.execute(sa.text("SELECT id, content FROM amc_import")).fetchall():
        data = bytes(content)
        sheets = conn.execute(sa.text("SELECT id, name FROM amc_import_sheet WHERE import_id = :i ORDER BY position"),
                              {"i": iid}).fetchall()
        conn.execute(sa.text("UPDATE amc_import SET active_sheet = :p WHERE id = :i"),
                     {"p": active_position(data, [n for _, n in sheets]), "i": iid})
        colors = tab_colors(data)
        for sid, name in sheets:
            if name in colors:
                conn.execute(sa.text("UPDATE amc_import_sheet SET tab_color = :c WHERE id = :s"),
                             {"c": colors[name], "s": sid})


def downgrade() -> None:
    with op.batch_alter_table("amc_import_sheet") as b:
        b.drop_column("tab_color")
    with op.batch_alter_table("amc_import") as b:
        b.drop_column("active_sheet")
