"""replace slide_projects with slide_sessions + slide_messages

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-26 13:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Mock-phase table is being replaced. Per Q2 we discard data instead of
    # migrating it to the new schema.
    op.drop_index("ix_slide_projects_owner_active", table_name="slide_projects")
    op.drop_table("slide_projects")

    slide_status = sa.Enum(
        "outlining", "rendering", "rendered", "failed",
        name="slide_status",
    )
    slide_status.create(op.get_bind(), checkfirst=True)

    slide_role = sa.Enum("user", "assistant", name="slide_role")
    slide_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "slide_sessions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.Text,
            nullable=False,
            server_default=sa.text("'New deck'"),
        ),
        sa.Column(
            "status",
            PG_ENUM("outlining", "rendering", "rendered", "failed",
                    name="slide_status", create_type=False),
            nullable=False,
            server_default=sa.text("'outlining'"),
        ),
        # SQLite object key for the most recently rendered PPTX. NULL until
        # the first successful render.
        sa.Column("generated_pptx_key", sa.Text, nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_slide_sessions_owner_active",
        "slide_sessions",
        ["owner_user_id", "updated_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "slide_messages",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "session_id",
            sa.BigInteger,
            sa.ForeignKey("slide_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "role",
            PG_ENUM("user", "assistant", name="slide_role", create_type=False),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        # Citations from RAG retrieval, same shape as chat_messages.citations.
        sa.Column("citations", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_slide_messages_session_id",
        "slide_messages",
        ["session_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_slide_messages_session_id", table_name="slide_messages")
    op.drop_table("slide_messages")
    op.drop_index("ix_slide_sessions_owner_active", table_name="slide_sessions")
    op.drop_table("slide_sessions")
    sa.Enum(name="slide_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="slide_status").drop(op.get_bind(), checkfirst=True)

    # Re-create slide_projects so a downgrade returns to the 0004 schema.
    op.create_table(
        "slide_projects",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "owner_user_id", sa.BigInteger,
            sa.ForeignKey("users.id"), nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("use_rag", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("kb_ids", JSONB, nullable=True),
        sa.Column("outline", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
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
