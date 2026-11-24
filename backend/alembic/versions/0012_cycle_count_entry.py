"""Cycle Count Planning: one saved copy of the masterlist per month.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cycle_count_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("month", sa.String(7), nullable=False, index=True),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("classification", sa.String(80), nullable=True),
        sa.Column("plant_location", sa.String(80), nullable=True),
        sa.Column("original_date", sa.Date(), nullable=False),
        sa.Column("adjusted_date", sa.Date(), nullable=True),
        sa.Column("in_charge", sa.String(120), nullable=True),
        sa.Column("last_edit", sa.String(300), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.UniqueConstraint("month", "code", name="uq_cycle_count_entry_month_code"),
    )
    op.drop_table("cycle_count_adjustment")


def downgrade() -> None:
    op.create_table(
        "cycle_count_adjustment",
        sa.Column("code", sa.String(120), primary_key=True),
        sa.Column("adjusted_date", sa.Date(), nullable=True),
        sa.Column("in_charge", sa.String(120), nullable=True),
        sa.Column("last_edit", sa.String(300), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
    )
    op.drop_table("cycle_count_entry")
