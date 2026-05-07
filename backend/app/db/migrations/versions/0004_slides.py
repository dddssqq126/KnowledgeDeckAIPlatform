"""slide_projects table (mock PPTX phase)

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "slide_projects",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("use_rag", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("kb_ids", JSONB, nullable=True),
        # Plain-text outline for the MVP mock. When Presenton lands this turns
        # into a download_key pointing at a generated PPTX in SQLite object storage.
        sa.Column("outline", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_slide_projects_owner_active",
        "slide_projects",
        ["owner_user_id", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_slide_projects_owner_active", table_name="slide_projects")
    op.drop_table("slide_projects")
