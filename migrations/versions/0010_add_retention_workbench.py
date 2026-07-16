"""Add retention workbench task, contact, and suppression records.

Revision ID: 0010_add_retention_workbench
Revises: 0009_remove_extra_demo_stylists
Create Date: 2026-07-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_add_retention_workbench"
down_revision: Union[str, None] = "0009_remove_extra_demo_stylists"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


task_status = sa.Enum(
    "PENDING_REVIEW", "SENDING", "SENT", "SEND_FAILED", "REPLIED",
    "MANUAL_FOLLOWUP", "COOLING", "IGNORED", "CLOSED",
    name="retentiontaskstatus",
)
contact_status = sa.Enum("ATTEMPTING", "SENT", "FAILED", name="retentioncontactstatus")
suppression_type = sa.Enum(
    "TEMPORARY_IGNORE", "PERMANENT_IGNORE", "UNSUBSCRIBED", "MANUAL_FOLLOWUP",
    name="retentionsuppressiontype",
)
reminder_type = sa.Enum("REPURCHASE", "BIRTHDAY", "CHURN_RISK", name="remindertype")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        task_status.create(bind, checkfirst=True)
        contact_status.create(bind, checkfirst=True)
        suppression_type.create(bind, checkfirst=True)

    op.create_table(
        "retention_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("stylist_id", sa.String(length=36), sa.ForeignKey("stylists.id")),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("primary_type", reminder_type, nullable=False),
        sa.Column("strategy_tags", sa.JSON(), nullable=False),
        sa.Column("trigger_reasons", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", task_status, nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("suggested_message", sa.Text()),
        sa.Column("suggested_coupon_id", sa.String(length=64)),
        sa.Column("suggestion_reason", sa.Text()),
        sa.Column("agent_trace_id", sa.String(length=64)),
        sa.Column("rule_version", sa.String(length=32), nullable=False, server_default="retention-v2"),
        sa.Column("next_contact_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("customer_id", "business_date", name="uq_retention_tasks_customer_business_date"),
    )
    op.create_index("ix_retention_tasks_status_next_contact", "retention_tasks", ["status", "next_contact_at"])

    op.create_table(
        "retention_contacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("retention_tasks.id"), nullable=False),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sender_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="mock"),
        sa.Column("status", contact_status, nullable=False, server_default="ATTEMPTING"),
        sa.Column("actual_message", sa.Text(), nullable=False),
        sa.Column("coupon_id", sa.String(length=64)),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("failed_at", sa.DateTime()),
        sa.Column("provider_message_id", sa.String(length=128)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("reply_content", sa.Text()),
        sa.Column("replied_at", sa.DateTime()),
        sa.Column("followup_status", sa.String(length=32)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_retention_contacts_customer_sent", "retention_contacts", ["customer_id", "sent_at"])

    op.create_table(
        "retention_suppressions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("suppression_type", suppression_type, nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime()),
        sa.Column("reason", sa.Text()),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("released_by", sa.String(length=36), sa.ForeignKey("users.id")),
        sa.Column("released_at", sa.DateTime()),
        sa.Column("release_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_retention_suppressions_customer_type", "retention_suppressions", ["customer_id", "suppression_type"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_retention_suppressions_customer_type", table_name="retention_suppressions")
    op.drop_table("retention_suppressions")
    op.drop_index("ix_retention_contacts_customer_sent", table_name="retention_contacts")
    op.drop_table("retention_contacts")
    op.drop_index("ix_retention_tasks_status_next_contact", table_name="retention_tasks")
    op.drop_table("retention_tasks")
    if bind.dialect.name != "sqlite":
        suppression_type.drop(bind, checkfirst=True)
        contact_status.drop(bind, checkfirst=True)
        task_status.drop(bind, checkfirst=True)
