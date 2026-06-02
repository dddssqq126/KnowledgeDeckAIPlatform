"""chat session type

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-02 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "chat_type",
            sa.Text,
            nullable=False,
            server_default="general",
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "chat_type")
