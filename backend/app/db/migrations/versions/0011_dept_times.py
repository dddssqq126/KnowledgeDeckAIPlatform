"""dept_times table

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-07 00:00:00

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
        "dept_times",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("dept", sa.Text, nullable=False),
        sa.Column(
            "time",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_dept_times_owner_time",
        "dept_times",
        ["owner_user_id", "time"],
    )


def downgrade() -> None:
    op.drop_index("ix_dept_times_owner_time", table_name="dept_times")
    op.drop_table("dept_times")
