"""Prevent more than one consumption ledger row per appointment."""

from typing import Sequence, Union

from alembic import op


revision: str = "0012_add_transaction_appointment_unique"
down_revision: Union[str, None] = "0011_add_stylist_time_slot_unique_constraint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_transactions_appointment_id",
            ["appointment_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint("uq_transactions_appointment_id", type_="unique")
