"""Remove the four demo stylists outside the H5 business scope.

Revision ID: 0009_remove_extra_demo_stylists
Revises: 0008_add_service_verification
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_remove_extra_demo_stylists"
down_revision: Union[str, None] = "0008_add_service_verification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EXTRA_STYLIST_PHONES = (
    "13800005555",
    "13800006666",
    "13800007777",
    "13800008888",
)


def upgrade() -> None:
    bind = op.get_bind()
    placeholders = ", ".join(f":phone_{index}" for index in range(len(EXTRA_STYLIST_PHONES)))
    params = {f"phone_{index}": phone for index, phone in enumerate(EXTRA_STYLIST_PHONES)}
    stylist_ids = f"SELECT id FROM stylists WHERE user_id IN (SELECT id FROM users WHERE phone IN ({placeholders}))"

    bind.execute(sa.text(f"DELETE FROM stylist_time_slots WHERE stylist_id IN ({stylist_ids})"), params)
    bind.execute(sa.text(f"DELETE FROM stylists WHERE id IN ({stylist_ids})"), params)
    bind.execute(sa.text(f"DELETE FROM users WHERE phone IN ({placeholders})"), params)


def downgrade() -> None:
    # Demo employees are intentionally not recreated during downgrade.
    pass
