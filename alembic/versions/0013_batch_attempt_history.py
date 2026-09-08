"""Keep failed batch attempts without overwriting their audit history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_batch_attempt_history"
down_revision = "0012_google_sync_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("batch_items", sa.Column("attempt_history", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("batch_items", "attempt_history")
