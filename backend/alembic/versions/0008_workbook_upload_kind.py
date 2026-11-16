"""Workbook uploads are shared by two modules: AMC Import (kind 'amc') and Physical Counting (kind 'counted',
the COUNTED LIST workbook). Existing uploads are AMC uploads.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("amc_import", sa.Column("kind", sa.String(20), nullable=False, server_default="amc"))
    op.create_index("ix_amc_import_kind", "amc_import", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_amc_import_kind", table_name="amc_import")
    with op.batch_alter_table("amc_import") as b:
        b.drop_column("kind")
