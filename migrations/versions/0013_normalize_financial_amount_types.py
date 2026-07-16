"""Use fixed two-decimal numeric columns for financial amounts."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013_normalize_financial_amount_types"
down_revision: Union[str, None] = "0012_add_transaction_appointment_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    amount_columns = {
        "users": ["total_spent"],
        "transactions": ["amount"],
        "service_packages": ["price"],
        "customer_packages": ["purchase_price"],
        "service_verifications": ["amount"],
    }
    for table_name, columns in amount_columns.items():
        with op.batch_alter_table(table_name) as batch_op:
            for column_name in columns:
                batch_op.alter_column(
                    column_name,
                    existing_type=sa.Float(),
                    type_=sa.Numeric(12, 2),
                )


def downgrade() -> None:
    amount_columns = {
        "users": ["total_spent"],
        "transactions": ["amount"],
        "service_packages": ["price"],
        "customer_packages": ["purchase_price"],
        "service_verifications": ["amount"],
    }
    for table_name, columns in amount_columns.items():
        with op.batch_alter_table(table_name) as batch_op:
            for column_name in columns:
                batch_op.alter_column(
                    column_name,
                    existing_type=sa.Numeric(12, 2),
                    type_=sa.Float(),
                )
