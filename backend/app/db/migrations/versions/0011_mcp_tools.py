"""mcp tools

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-02 00:00:00

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
        "mcp_tools",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("query_name", sa.Text(), nullable=False),
        sa.Column("server_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("transport", sa.Text(), nullable=False, server_default="in-process"),
        sa.Column("method", sa.Text(), nullable=False, server_default="POST"),
        sa.Column("endpoint", sa.Text(), nullable=False, server_default=""),
        sa.Column("template_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("timeout_sec", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("status", sa.Text(), nullable=False, server_default="enabled"),
        sa.Column("input_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("output_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("built_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("handler_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "uq_mcp_tools_global_query_name",
        "mcp_tools",
        ["query_name"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NULL"),
        sqlite_where=sa.text("owner_user_id IS NULL"),
    )
    op.create_index(
        "uq_mcp_tools_owner_query_name",
        "mcp_tools",
        ["owner_user_id", "query_name"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
        sqlite_where=sa.text("owner_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_mcp_tools_owner_query_name", table_name="mcp_tools")
    op.drop_index("uq_mcp_tools_global_query_name", table_name="mcp_tools")
    op.drop_table("mcp_tools")
