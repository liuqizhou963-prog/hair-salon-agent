"""Add WeChat identity and allow accounts without a bound phone.

Revision ID: 0007_add_wechat_auth
Revises: 0006_repair_member_expiry
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_add_wechat_auth"
down_revision: Union[str, None] = "0006_repair_member_expiry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("wechat_openid", sa.String(length=64), nullable=True))
            batch_op.alter_column("phone", existing_type=sa.String(length=20), nullable=True)
    else:
        op.add_column("users", sa.Column("wechat_openid", sa.String(length=64), nullable=True))
        op.alter_column("users", "phone", existing_type=sa.String(length=20), nullable=True)
    op.create_index("uq_users_wechat_openid", "users", ["wechat_openid"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_wechat_openid", table_name="users")
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users", recreate="always") as batch_op:
            batch_op.drop_column("wechat_openid")
            batch_op.alter_column("phone", existing_type=sa.String(length=20), nullable=False)
    else:
        op.drop_column("users", "wechat_openid")
        op.alter_column("users", "phone", existing_type=sa.String(length=20), nullable=False)
