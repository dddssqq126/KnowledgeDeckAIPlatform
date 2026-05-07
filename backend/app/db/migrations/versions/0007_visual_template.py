"""swap slide_sessions.template_files → custom_template_id/name

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-26 15:00:00

The previous template_files JSONB stored uploaded PPTXs that we re-uploaded
to Presenton's `files` parameter as RAG-style content references — that is
NOT what users typically mean by "upload a template". Replace with a single
custom_template_id pointing at a Presenton-authored visual template (built
via Presenton's /custom-template UI; we proxy /api/v1/ppt/template/all to
let the user pick).

Migration discards the previous PPTX bytes — they're orphaned in SQLite object storage; a
future cleanup job can remove them. The slide-sessions feature is freshly
built so production data loss is not a concern.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slide_sessions",
        sa.Column("custom_template_id", sa.Text, nullable=True),
    )
    op.add_column(
        "slide_sessions",
        sa.Column("custom_template_name", sa.Text, nullable=True),
    )
    op.drop_column("slide_sessions", "template_files")


def downgrade() -> None:
    op.add_column(
        "slide_sessions",
        sa.Column(
            "template_files",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.drop_column("slide_sessions", "custom_template_name")
    op.drop_column("slide_sessions", "custom_template_id")
