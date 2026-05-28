"""file vendor/platform tags

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-28 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("files", sa.Column("tag_vendor", sa.Text(), nullable=True))
    op.add_column("files", sa.Column("tag_platform", sa.Text(), nullable=True))
    op.add_column("files", sa.Column("tag_knowledge_type", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("files", "tag_knowledge_type")
    op.drop_column("files", "tag_platform")
    op.drop_column("files", "tag_vendor")
