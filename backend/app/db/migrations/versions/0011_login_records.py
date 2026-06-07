"""login records

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-03 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_records",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("dept_name", sa.Text(), nullable=True),
        sa.Column("chinese_name", sa.Text(), nullable=True),
        sa.Column("dept_id", sa.Text(), nullable=True),
        sa.Column("emp_id", sa.Text(), nullable=True),
        sa.Column("user_account_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_login_records_user_account_name",
        "login_records",
        ["user_account_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_login_records_user_account_name", table_name="login_records")
    op.drop_table("login_records")
