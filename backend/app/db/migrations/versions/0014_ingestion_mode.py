"""Split document and image ingestion modes."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    mode_type = postgresql.ENUM(
        "document", "image", "both", name="ingestion_mode", create_type=False
    )
    if bind.dialect.name == "postgresql":
        mode_type.create(bind, checkfirst=True)
    op.add_column(
        "files",
        sa.Column("ingestion_mode", mode_type, nullable=False, server_default="both"),
    )
    op.drop_index("uq_files_kb_filename_active", table_name="files")
    op.create_index(
        "uq_files_kb_filename_active",
        "files",
        ["knowledge_base_id", "filename", "ingestion_mode"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.alter_column("files", "ingestion_mode", server_default=None)


def downgrade() -> None:
    op.drop_index("uq_files_kb_filename_active", table_name="files")
    op.create_index(
        "uq_files_kb_filename_active",
        "files",
        ["knowledge_base_id", "filename"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_column("files", "ingestion_mode")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="ingestion_mode").drop(bind, checkfirst=True)
