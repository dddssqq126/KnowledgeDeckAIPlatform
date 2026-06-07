"""chat attachments and feedback comments

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
        "chat_message_attachments",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "message_id",
            sa.BigInteger,
            sa.ForeignKey("chat_messages.id"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id"),
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
        "ix_chat_message_attachments_message_id",
        "chat_message_attachments",
        ["message_id"],
    )
    op.create_index(
        "ix_chat_message_attachments_owner_id",
        "chat_message_attachments",
        ["owner_user_id"],
    )
    op.add_column(
        "chat_message_feedbacks",
        sa.Column("comment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message_feedbacks", "comment")
    op.drop_index(
        "ix_chat_message_attachments_owner_id",
        table_name="chat_message_attachments",
    )
    op.drop_index(
        "ix_chat_message_attachments_message_id",
        table_name="chat_message_attachments",
    )
    op.drop_table("chat_message_attachments")
