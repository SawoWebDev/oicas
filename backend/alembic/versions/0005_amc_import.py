"""amc_import / amc_import_sheet: uploaded copies of the AMC / ABC Analysis workbook (AMC Import module)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "amc_import",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by", sa.String(length=200), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("sheet_count", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
    )
    op.create_table(
        "amc_import_sheet",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("amc_import.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("n_rows", sa.Integer(), nullable=False),
        sa.Column("n_cols", sa.Integer(), nullable=False),
        sa.Column("header_row", sa.Integer(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("merges", sa.JSON(), nullable=False),
        sa.UniqueConstraint("import_id", "position"),
    )
    op.create_index("ix_amc_import_sheet_import_id", "amc_import_sheet", ["import_id"])


def downgrade() -> None:
    op.drop_index("ix_amc_import_sheet_import_id", table_name="amc_import_sheet")
    op.drop_table("amc_import_sheet")
    op.drop_table("amc_import")
