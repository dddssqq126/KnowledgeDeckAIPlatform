"""project mapping and file project metadata"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

def upgrade() -> None:
    op.create_table("projects", sa.Column("id", ID, primary_key=True), sa.Column("owner_user_id", ID, sa.ForeignKey("users.id"), nullable=False), sa.Column("project_id", sa.Text(), nullable=False), sa.Column("canonical_name", sa.Text(), nullable=False), sa.Column("model_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")), sa.Column("status", sa.Text()), sa.Column("summary", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("uq_projects_owner_project_id", "projects", ["owner_user_id", "project_id"], unique=True)
    op.create_table("project_aliases", sa.Column("id", ID, primary_key=True), sa.Column("project_pk", ID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False), sa.Column("normalized_alias", sa.Text(), nullable=False), sa.Column("display_alias", sa.Text(), nullable=False))
    op.create_index("ix_project_aliases_normalized", "project_aliases", ["normalized_alias"])
    op.add_column("files", sa.Column("project_id", sa.Text()))
    op.add_column("files", sa.Column("model_codes", sa.JSON()))

def downgrade() -> None:
    op.drop_column("files", "model_codes"); op.drop_column("files", "project_id")
    op.drop_index("ix_project_aliases_normalized", table_name="project_aliases"); op.drop_table("project_aliases")
    op.drop_index("uq_projects_owner_project_id", table_name="projects"); op.drop_table("projects")
