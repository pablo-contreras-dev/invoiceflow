"""Add human review decisions and audit events.

Revision ID: 0003_manual_review_audit
Revises: 0002_idempotency
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_manual_review_audit"
down_revision = "0002_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoice_records", sa.Column("review_decision", sa.String(length=12), nullable=True))
    op.add_column("invoice_records", sa.Column("reviewed_by", sa.String(length=120), nullable=True))
    op.add_column("invoice_records", sa.Column("review_note", sa.String(length=500), nullable=True))
    op.add_column("invoice_records", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "invoice_review_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("invoice_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=12), nullable=False),
        sa.Column("reviewer", sa.String(length=120), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invoice_review_events_invoice_id", "invoice_review_events", ["invoice_id"])


def downgrade() -> None:
    op.drop_index("ix_invoice_review_events_invoice_id", table_name="invoice_review_events")
    op.drop_table("invoice_review_events")
    op.drop_column("invoice_records", "reviewed_at")
    op.drop_column("invoice_records", "review_note")
    op.drop_column("invoice_records", "reviewed_by")
    op.drop_column("invoice_records", "review_decision")
