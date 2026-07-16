"""Add a database uniqueness guard for generated stylist time slots."""

from typing import Sequence, Union

from alembic import op


revision: str = "0011_add_stylist_time_slot_unique_constraint"
down_revision: Union[str, None] = "0010_add_retention_workbench"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("stylist_time_slots") as batch_op:
        batch_op.create_unique_constraint(
            "uq_stylist_time_slots_stylist_date_time",
            ["stylist_id", "date", "time"],
        )


def downgrade() -> None:
    with op.batch_alter_table("stylist_time_slots") as batch_op:
        batch_op.drop_constraint(
            "uq_stylist_time_slots_stylist_date_time",
            type_="unique",
        )
