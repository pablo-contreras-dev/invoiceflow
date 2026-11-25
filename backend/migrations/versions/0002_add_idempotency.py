"""Add idempotency support to invoice intake.

Revision ID: 0002_idempotency
Revises: 0001_invoice_records
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_idempotency"
down_revision = "0001_invoice_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoice_records", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("invoice_records", sa.Column("request_hash", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_invoice_records_idempotency_key",
        "invoice_records",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_invoice_records_idempotency_key", table_name="invoice_records")
    op.drop_column("invoice_records", "request_hash")
    op.drop_column("invoice_records", "idempotency_key")
