"""Bind access cycles to their live isolated browser session."""

from alembic import op
import sqlalchemy as sa

revision = "0024_access_cycle_session"
down_revision = "0023_cleanup_retired_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("access_cycles", sa.Column("browser_target_id", sa.String(128)))
    op.add_column("access_cycles", sa.Column("browser_context_id", sa.String(128)))
    op.add_column("access_cycles", sa.Column("manual_validation_requested_at", sa.DateTime(timezone=True)))


def downgrade():
    for column in ("manual_validation_requested_at", "browser_context_id", "browser_target_id"):
        op.drop_column("access_cycles", column)
