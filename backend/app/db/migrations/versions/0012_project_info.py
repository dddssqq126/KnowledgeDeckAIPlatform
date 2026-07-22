"""project information lookup

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-22 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_info",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("customer_code", sa.Text(), nullable=True),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("project_name", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("project_data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_project_info_customer_code", "project_info", ["customer_code"])
    op.create_index("ix_project_info_customer_name", "project_info", ["customer_name"])
    op.create_index("ix_project_info_project_name", "project_info", ["project_name"])
    op.create_index("ix_project_info_model_id", "project_info", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_project_info_model_id", table_name="project_info")
    op.drop_index("ix_project_info_project_name", table_name="project_info")
    op.drop_index("ix_project_info_customer_name", table_name="project_info")
    op.drop_index("ix_project_info_customer_code", table_name="project_info")
    op.drop_table("project_info")
