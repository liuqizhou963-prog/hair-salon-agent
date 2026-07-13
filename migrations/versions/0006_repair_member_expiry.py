"""Repair member expiry column when migration version was stamped early.

Revision ID: 0006_repair_member_expiry
Revises: 0005_add_member_expiry
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_repair_member_expiry"
down_revision: Union[str, None] = "0005_add_member_expiry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("members")}
    if "expires_at" not in columns:
        op.add_column("members", sa.Column("expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("members")}
    if "expires_at" in columns:
        op.drop_column("members", "expires_at")
