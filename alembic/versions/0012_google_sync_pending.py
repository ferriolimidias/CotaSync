"""Persist outbound Google changes independently from action execution."""
from alembic import op
import sqlalchemy as sa

revision = "0012_google_sync_pending"
down_revision = "0011_google_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_sync_pending",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("connector_id", sa.String(128), sa.ForeignKey("spreadsheet_connectors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("spreadsheet_id", sa.String(128), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(128), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("field_id", sa.String(128), sa.ForeignKey("data_source_fields.id", ondelete="SET NULL"), nullable=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("batch_id", sa.String(128), sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("run_id", sa.String(128), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("connector_id", "client_id", "field_id", name="uq_google_pending_target"),
    )
    op.create_index("ix_google_sync_pending_status", "google_sync_pending", ["status"])


def downgrade() -> None:
    op.drop_index("ix_google_sync_pending_status", table_name="google_sync_pending")
    op.drop_table("google_sync_pending")
