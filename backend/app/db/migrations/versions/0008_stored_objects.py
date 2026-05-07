"""stored object blobs

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-07 00:00:00

Persist object storage bytes in the relational database for local SQLite
installations while preserving the same bucket/key object-storage API.
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
        "stored_objects",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column(
            "size_bytes",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("data", sa.LargeBinary(), nullable=False),
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
        "uq_stored_objects_bucket_key",
        "stored_objects",
        ["bucket", "key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_stored_objects_bucket_key", table_name="stored_objects")
    op.drop_table("stored_objects")
