"""make data sources the canonical system spreadsheets and add connectors"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_system_spreadsheets"
down_revision = "0007_ai_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("system_spreadsheet_id", sa.String(128), nullable=True))
    op.create_index("ix_clients_system_spreadsheet_id", "clients", ["system_spreadsheet_id"])
    op.create_table(
        "spreadsheet_connectors",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("spreadsheet_id", sa.String(128), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector_type", sa.String(32), nullable=False),
        sa.Column("configuration", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_spreadsheet_connectors_spreadsheet_id", "spreadsheet_connectors", ["spreadsheet_id"])
    op.create_index("ix_spreadsheet_connectors_connector_type", "spreadsheet_connectors", ["connector_type"])
    op.create_index("ix_spreadsheet_connectors_status", "spreadsheet_connectors", ["status"])


def downgrade():
    op.drop_index("ix_spreadsheet_connectors_status", table_name="spreadsheet_connectors")
    op.drop_index("ix_spreadsheet_connectors_connector_type", table_name="spreadsheet_connectors")
    op.drop_index("ix_spreadsheet_connectors_spreadsheet_id", table_name="spreadsheet_connectors")
    op.drop_table("spreadsheet_connectors")
    op.drop_index("ix_clients_system_spreadsheet_id", table_name="clients")
    op.drop_column("clients", "system_spreadsheet_id")
