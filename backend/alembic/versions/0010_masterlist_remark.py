"""Remarks typed on the Inventory Masterlist page.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "masterlist_remark",
        sa.Column("code", sa.String(120), primary_key=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("masterlist_remark")
