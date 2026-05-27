"""chat message feedback table

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-26 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


chat_feedback_type = sa.Enum("like", "dislike", name="chat_feedback_type")


def upgrade() -> None:
    # op.create_table below auto-emits CREATE TYPE for the enum column on
    # Postgres; an explicit create here would duplicate it (the implicit one
    # doesn't use checkfirst). On SQLite the enum is just VARCHAR + CHECK.
    op.create_table(
        "chat_message_feedbacks",
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
        sa.Column("feedback", chat_feedback_type, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
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
    op.create_index(
        "uq_chat_message_feedback_owner",
        "chat_message_feedbacks",
        ["message_id", "owner_user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_chat_message_feedback_owner", table_name="chat_message_feedbacks")
    op.drop_table("chat_message_feedbacks")
    bind = op.get_bind()
    chat_feedback_type.drop(bind, checkfirst=True)
