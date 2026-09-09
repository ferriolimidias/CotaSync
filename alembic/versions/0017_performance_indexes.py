"""Add indexes used by report ordering."""

from alembic import op


revision = "0017_performance_indexes"
down_revision = "0016_access_profile_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_runs_created_at", "runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_runs_created_at", table_name="runs")
