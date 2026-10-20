"""reconciliation.balance_source (odoo / legacy / book)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("reconciliation") as b:
        b.add_column(sa.Column("balance_source", sa.String(length=10), nullable=True))
    op.execute("UPDATE reconciliation SET balance_source = 'odoo' WHERE snapshot_id IN "
               "(SELECT id FROM inventory_snapshot WHERE source = 'odoo')")
    op.execute("UPDATE reconciliation SET balance_source = 'legacy' WHERE balance_source IS NULL "
               "AND snapshot_id IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("reconciliation") as b:
        b.drop_column("balance_source")
