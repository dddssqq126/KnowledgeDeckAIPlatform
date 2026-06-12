"""chat session share tokens

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-07 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_session_shares",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "session_id",
            sa.BigInteger,
            sa.ForeignKey("chat_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("token", sa.Text, nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_chat_session_active_share",
        "chat_session_shares",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_chat_session_shares_token_active",
        "chat_session_shares",
        ["token", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_session_shares_token_active", table_name="chat_session_shares"
    )
    op.drop_index("uq_chat_session_active_share", table_name="chat_session_shares")
    op.drop_table("chat_session_shares")
