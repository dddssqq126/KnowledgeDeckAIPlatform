"""slide_sessions.template_files JSONB column

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-26 14:30:00

Stores reference PPTX templates attached to a slide session. The shape is
a JSONB array of {filename, storage_key, size_bytes} objects. Bytes live
in local object storage (so Presenton restarts don't break references); render-time
flow re-uploads each file to Presenton to obtain a fresh path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "slide_sessions",
        sa.Column(
            "template_files",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("slide_sessions", "template_files")
