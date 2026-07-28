"""PPTX knowledge images and chat related images."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "knowledge_images",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "file_id",
            ID,
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", ID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "knowledge_base_id",
            ID,
            sa.ForeignKey("knowledge_bases.id"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("image_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("page_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("extension", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", ID, nullable=False),
        sa.Column("width_emu", ID),
        sa.Column("height_emu", ID),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column(
            "indexed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_knowledge_images_file_id", "knowledge_images", ["file_id"]
    )
    op.create_index(
        "ix_knowledge_images_owner_kb",
        "knowledge_images",
        ["owner_user_id", "knowledge_base_id"],
    )
    op.create_index(
        "uq_knowledge_images_file_hash",
        "knowledge_images",
        ["file_id", "content_sha256"],
        unique=True,
    )
    op.add_column("chat_messages", sa.Column("related_images", sa.JSON()))


def downgrade() -> None:
    op.drop_column("chat_messages", "related_images")
    op.drop_index(
        "uq_knowledge_images_file_hash", table_name="knowledge_images"
    )
    op.drop_index("ix_knowledge_images_owner_kb", table_name="knowledge_images")
    op.drop_index("ix_knowledge_images_file_id", table_name="knowledge_images")
    op.drop_table("knowledge_images")
