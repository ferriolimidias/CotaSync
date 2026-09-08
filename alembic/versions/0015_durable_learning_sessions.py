"""Persist learning sessions independently from the backend process."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_durable_learning_sessions"
down_revision = "0014_access_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_sessions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
        sa.Column("action_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("expected_result", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("recording_status", sa.String(32), nullable=False, server_default="not_started"),
        sa.Column("publication_status", sa.String(32), nullable=False, server_default="not_attempted"),
        sa.Column("external_system_id", sa.String(128), sa.ForeignKey("external_systems.id", ondelete="SET NULL")),
        sa.Column("access_profile_id", sa.String(128), sa.ForeignKey("external_access_profiles.id", ondelete="SET NULL")),
        sa.Column("allowed_list_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("run_start_strategy", sa.String(64), nullable=False, server_default="persistent_graph_reentry"),
        sa.Column("raw_events", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("recorded_steps", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("bootstrap_metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("state_evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("variable_bindings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("outputs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("publication_error_code", sa.String(128)),
        sa.Column("publication_error_stage", sa.String(128)),
        sa.Column("publication_error_message", sa.Text()),
        sa.Column("published_action_id", sa.String(255)),
        sa.Column("published_action_version_id", sa.String(128)),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("recording_started_at", sa.DateTime(timezone=True)),
        sa.Column("recording_stopped_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_learning_sessions_tenant_id", "learning_sessions", ["tenant_id"])
    op.create_index("ix_learning_sessions_status", "learning_sessions", ["status"])
    op.create_index("ix_learning_sessions_recording_status", "learning_sessions", ["recording_status"])
    op.create_index("ix_learning_sessions_publication_status", "learning_sessions", ["publication_status"])
    op.create_index("ix_learning_sessions_external_system_id", "learning_sessions", ["external_system_id"])
    op.create_index("ix_learning_sessions_access_profile_id", "learning_sessions", ["access_profile_id"])


def downgrade() -> None:
    for name in (
        "ix_learning_sessions_access_profile_id",
        "ix_learning_sessions_external_system_id",
        "ix_learning_sessions_publication_status",
        "ix_learning_sessions_recording_status",
        "ix_learning_sessions_status",
        "ix_learning_sessions_tenant_id",
    ):
        op.drop_index(name, table_name="learning_sessions")
    op.drop_table("learning_sessions")
