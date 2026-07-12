"""Create the initial salon schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False, unique=True),
        sa.Column("email", sa.String(length=100), unique=True),
        sa.Column("role", sa.Enum("CUSTOMER", "STYLIST", "ADMIN", name="userrole")),
        sa.Column("birthday", sa.String(length=10)),
        sa.Column("total_spent", sa.Float(), default=0),
        sa.Column("last_visit", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_table(
        "stylists",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("specialty", sa.String(length=500)),
        sa.Column("experience_years", sa.Integer(), default=0),
        sa.Column("rating", sa.Float(), default=5.0),
        sa.Column("bio", sa.Text()),
        sa.Column("is_available", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "stylist_time_slots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("stylist_id", sa.String(length=36), sa.ForeignKey("stylists.id"), nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("time", sa.String(length=5), nullable=False),
        sa.Column("is_booked", sa.Boolean(), default=False),
        sa.Column("booked_by_appointment_id", sa.String(length=36)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "appointments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("stylist_id", sa.String(length=36), sa.ForeignKey("stylists.id"), nullable=False),
        sa.Column("time_slot_id", sa.String(length=36), sa.ForeignKey("stylist_time_slots.id"), nullable=False),
        sa.Column("service", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("status", sa.Enum("PENDING", "CONFIRMED", "COMPLETED", "CANCELLED", name="appointmentstatus")),
        sa.Column("appointment_datetime", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_table(
        "members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("level", sa.Enum("SILVER", "GOLD", "PLATINUM", name="memberlevel")),
        sa.Column("points", sa.Integer(), default=0),
        sa.Column("birthday_bonus_claimed", sa.Boolean(), default=False),
        sa.Column("joined_date", sa.DateTime()),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("appointment_id", sa.String(length=36), sa.ForeignKey("appointments.id")),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("service", sa.String(length=100)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "reminder_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("stylist_id", sa.String(length=36), sa.ForeignKey("stylists.id")),
        sa.Column("reminder_type", sa.Enum("REPURCHASE", "BIRTHDAY", "CHURN_RISK", name="remindertype"), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "CONTACTED", "DISMISSED", name="reminderstatus")),
        sa.Column("priority", sa.Integer(), default=0),
        sa.Column("reason", sa.String(length=255)),
        sa.Column("suggested_message", sa.Text()),
        sa.Column("reference_date", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("contacted_at", sa.DateTime()),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_stylist_slots_booked_appointment",
            "stylist_time_slots",
            "appointments",
            ["booked_by_appointment_id"],
            ["id"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_stylist_slots_booked_appointment",
            "stylist_time_slots",
            type_="foreignkey",
        )
    op.drop_table("reminder_logs")
    op.drop_table("transactions")
    op.drop_table("members")
    op.drop_table("appointments")
    op.drop_table("stylist_time_slots")
    op.drop_table("stylists")
    op.drop_table("users")
