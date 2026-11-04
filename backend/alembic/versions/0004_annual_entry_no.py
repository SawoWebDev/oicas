"""annual_inventory_entry.entry_no: running entry number per plant / area / section (series starts at 40900)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

START = 40900


def upgrade() -> None:
    op.add_column("annual_inventory_entry", sa.Column("entry_no", sa.Integer(), nullable=True))
    # number the rows that already exist, oldest first, from 40900 within each plant / area / section
    conn = op.get_bind()
    nxt: dict[tuple, int] = {}
    for rid, p, a, s in conn.execute(sa.text(
            "SELECT id, period, area, section FROM annual_inventory_entry ORDER BY id")).fetchall():
        n = nxt.get((p, a, s), START)
        conn.execute(sa.text("UPDATE annual_inventory_entry SET entry_no = :n WHERE id = :i"), {"n": n, "i": rid})
        nxt[(p, a, s)] = n + 1
    with op.batch_alter_table("annual_inventory_entry") as b:
        b.alter_column("entry_no", existing_type=sa.Integer(), nullable=False)
    op.create_index("ux_annual_entry_no", "annual_inventory_entry", ["period", "area", "section", "entry_no"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_annual_entry_no", table_name="annual_inventory_entry")
    with op.batch_alter_table("annual_inventory_entry") as b:
        b.drop_column("entry_no")
