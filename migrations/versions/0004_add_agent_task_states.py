"""Add persisted state for agent workflows.

Revision ID: 0004_add_agent_task_states
Revises: 0003_add_finance_and_notification_tables
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_add_agent_task_states"
down_revision: Union[str, None] = "0003_add_finance_and_notification_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_task_states",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("requester_id", sa.String(length=36), sa.ForeignKey("users.id")),
        sa.Column("workflow_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "RUNNING", "AWAITING_CONFIRMATION", "COMPLETED", "FAILED", name="agenttaskstatus"), nullable=False),
        sa.Column("input_payload", sa.Text()),
        sa.Column("result_payload", sa.Text()),
        sa.Column("awaiting_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("agent_task_states")
