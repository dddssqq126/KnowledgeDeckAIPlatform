"""chat input files table

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-07 00:10:00

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
        "chat_input_files",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.BigInteger,
            sa.ForeignKey("chat_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.BigInteger,
            sa.ForeignKey("chat_messages.id"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("extension", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("content_sha256", sa.Text, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_chat_input_files_owner_created",
        "chat_input_files",
        ["owner_user_id", "created_at"],
    )
    op.create_index(
        "ix_chat_input_files_session_message",
        "chat_input_files",
        ["session_id", "message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_input_files_session_message", table_name="chat_input_files")
    op.drop_index("ix_chat_input_files_owner_created", table_name="chat_input_files")
    op.drop_table("chat_input_files")
