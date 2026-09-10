"""Persist asynchronous canonical external access cycles."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0018_access_cycles"
down_revision = "0017_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_cycles",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("external_system_id", sa.String(128), sa.ForeignKey("external_systems.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_profile_id", sa.String(128), sa.ForeignKey("external_access_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="starting"),
        sa.Column("stage", sa.String(64), nullable=False, server_default="access_start"),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message", sa.Text),
        sa.Column("events", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_access_cycles_status", "access_cycles", ["status"])
    op.create_index("ix_access_cycles_external_system_id", "access_cycles", ["external_system_id"])
    op.create_index("ix_access_cycles_access_profile_id", "access_cycles", ["access_profile_id"])


def downgrade() -> None:
    op.drop_index("ix_access_cycles_access_profile_id", table_name="access_cycles")
    op.drop_index("ix_access_cycles_external_system_id", table_name="access_cycles")
    op.drop_index("ix_access_cycles_status", table_name="access_cycles")
    op.drop_table("access_cycles")
