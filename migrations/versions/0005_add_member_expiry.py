"""Add member expiry date for retention segmentation.

Revision ID: 0005_add_member_expiry
Revises: 0004_add_agent_task_states
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_add_member_expiry"
down_revision: Union[str, None] = "0004_add_agent_task_states"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("members", sa.Column("expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("members", "expires_at")

