"""Create invoice records table.

Revision ID: 0001_invoice_records
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_invoice_records"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_name", sa.String(length=200), nullable=False),
        sa.Column("supplier_tax_id", sa.String(length=32), nullable=False),
        sa.Column("invoice_number", sa.String(length=80), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("net_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reasons", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("duplicate_of_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invoice_supplier_invoice", "invoice_records", ["supplier_tax_id", "invoice_number"])
    op.create_index("ix_invoice_records_status", "invoice_records", ["status"])


def downgrade() -> None:
    op.drop_index("ix_invoice_records_status", table_name="invoice_records")
    op.drop_index("ix_invoice_supplier_invoice", table_name="invoice_records")
    op.drop_table("invoice_records")
