"""add generic learning data sources and fields"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_learning_sources"
down_revision = "0005_user_auth_version"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("schema_metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("configuration", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_data_sources_source_type", "data_sources", ["source_type"])
    op.create_index("ix_data_sources_status", "data_sources", ["status"])
    op.create_table(
        "data_source_fields",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("data_source_id", sa.String(128), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("source_column_reference", sa.String(255), nullable=False),
        sa.Column("semantic_role", sa.String(64)),
        sa.Column("data_type", sa.String(32), nullable=False, server_default="string"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_data_source_fields_data_source_id", "data_source_fields", ["data_source_id"])


def downgrade():
    op.drop_index("ix_data_source_fields_data_source_id", table_name="data_source_fields")
    op.drop_table("data_source_fields")
    op.drop_index("ix_data_sources_status", table_name="data_sources")
    op.drop_index("ix_data_sources_source_type", table_name="data_sources")
    op.drop_table("data_sources")
