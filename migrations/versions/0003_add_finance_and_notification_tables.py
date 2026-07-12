"""Add wallet, refund, point, notification, and audit tables.

Revision ID: 0003_add_finance_and_notification_tables
Revises: 0002_add_user_auth_fields
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_add_finance_and_notification_tables"
down_revision: Union[str, None] = "0002_add_user_auth_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wallet_accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("balance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("wallet_id", sa.String(length=36), sa.ForeignKey("wallet_accounts.id"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("direction", sa.Enum("CREDIT", "DEBIT", name="walletdirection"), nullable=False),
        sa.Column("transaction_type", sa.Enum("RECHARGE", "PURCHASE", "REFUND", "ADJUSTMENT", name="wallettransactiontype"), nullable=False),
        sa.Column("balance_after_cents", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(length=50)),
        sa.Column("reference_id", sa.String(length=36)),
        sa.Column("note", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "refund_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "APPROVED", "REJECTED", name="refundstatus"), nullable=False),
        sa.Column("reason", sa.String(length=255)),
        sa.Column("processed_by", sa.String(length=36), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("processed_at", sa.DateTime()),
    )
    op.create_table(
        "point_transactions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=50)),
        sa.Column("source_id", sa.String(length=36)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.Enum("APPOINTMENT", "WALLET", "REFUND", "MARKETING", "SYSTEM", name="notificationkind"), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("read_at", sa.DateTime()),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("actor_user_id", sa.String(length=36), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("notifications")
    op.drop_table("point_transactions")
    op.drop_table("refund_requests")
    op.drop_table("wallet_transactions")
    op.drop_table("wallet_accounts")
