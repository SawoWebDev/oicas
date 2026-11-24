"""Cycle Count Planning: adjusted dates and in-charge per code.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cycle_count_adjustment",
        sa.Column("code", sa.String(120), primary_key=True),
        sa.Column("adjusted_date", sa.Date(), nullable=True),
        sa.Column("in_charge", sa.String(120), nullable=True),
        sa.Column("last_edit", sa.String(300), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("cycle_count_adjustment")
