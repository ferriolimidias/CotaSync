"""Persist the access cycle that gates a learning session."""

from alembic import op
import sqlalchemy as sa


revision = "0021_learning_access_cycle"
down_revision = "0020_access_cycle_worker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("learning_sessions", sa.Column("access_cycle_id", sa.String(128), nullable=True))
    op.create_index("ix_learning_sessions_access_cycle_id", "learning_sessions", ["access_cycle_id"])


def downgrade() -> None:
    op.drop_index("ix_learning_sessions_access_cycle_id", table_name="learning_sessions")
    op.drop_column("learning_sessions", "access_cycle_id")
