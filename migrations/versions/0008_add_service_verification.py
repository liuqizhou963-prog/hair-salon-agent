"""Add service packages and staff-controlled service verification.

Revision ID: 0008_add_service_verification
Revises: 0007_add_wechat_auth
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_add_service_verification"
down_revision: Union[str, None] = "0007_add_wechat_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_packages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("service", sa.String(length=100), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("total_uses", sa.Integer(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "customer_packages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("package_id", sa.String(length=36), sa.ForeignKey("service_packages.id"), nullable=False),
        sa.Column("purchase_price", sa.Float(), nullable=False),
        sa.Column("total_uses", sa.Integer(), nullable=False),
        sa.Column("remaining_uses", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("ACTIVE", "EXPIRED", "EXHAUSTED", "CANCELLED", name="customerpackagestatus"), nullable=False),
        sa.Column("purchased_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "service_verifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("appointment_id", sa.String(length=36), sa.ForeignKey("appointments.id"), nullable=False, unique=True),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("stylist_id", sa.String(length=36), sa.ForeignKey("stylists.id"), nullable=False),
        sa.Column("customer_package_id", sa.String(length=36), sa.ForeignKey("customer_packages.id")),
        sa.Column("service", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.Enum("VERIFIED", "COMPLETED", "CANCELLED", name="serviceverificationstatus"), nullable=False),
        sa.Column("verified_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_customer_packages_customer_id", "customer_packages", ["customer_id"])
    op.create_index("ix_service_verifications_stylist_id", "service_verifications", ["stylist_id"])


def downgrade() -> None:
    op.drop_index("ix_service_verifications_stylist_id", table_name="service_verifications")
    op.drop_index("ix_customer_packages_customer_id", table_name="customer_packages")
    op.drop_table("service_verifications")
    op.drop_table("customer_packages")
    op.drop_table("service_packages")
