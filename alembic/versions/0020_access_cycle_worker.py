"""Track the worker that atomically claimed an access cycle."""

from alembic import op
import sqlalchemy as sa

revision = "0020_access_cycle_worker"
down_revision = "0019_access_cycle_entry_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_cycles", sa.Column("worker_id", sa.String(128), nullable=True))
    op.create_index("ix_access_cycles_worker_id", "access_cycles", ["worker_id"])


def downgrade() -> None:
    op.drop_index("ix_access_cycles_worker_id", table_name="access_cycles")
    op.drop_column("access_cycles", "worker_id")
