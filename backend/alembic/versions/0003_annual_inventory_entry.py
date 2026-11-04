"""annual_inventory_entry: Annual Inventory log (P1-P4, Warehouse/Production, sections)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "annual_inventory_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period", sa.String(length=4), nullable=False),
        sa.Column("area", sa.String(length=20), nullable=False),
        sa.Column("section", sa.Integer(), nullable=False),
        sa.Column("item_code", sa.String(length=120), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("location", sa.String(length=120), nullable=False),
        sa.Column("remarks", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
    )
    op.create_index("ix_annual_scope", "annual_inventory_entry", ["period", "area", "section"])
    op.create_index("ix_annual_inventory_entry_item_code", "annual_inventory_entry", ["item_code"])


def downgrade() -> None:
    op.drop_index("ix_annual_inventory_entry_item_code", table_name="annual_inventory_entry")
    op.drop_index("ix_annual_scope", table_name="annual_inventory_entry")
    op.drop_table("annual_inventory_entry")
