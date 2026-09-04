"""Make action scope semantics explicit."""
from alembic import op
import sqlalchemy as sa

revision = "0010_action_scope"
down_revision = "0009_client_lists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("actions", sa.Column("scope_mode", sa.String(16), nullable=False, server_default="all"))
    op.execute("UPDATE actions SET scope_mode = 'selected' WHERE jsonb_array_length(coalesce(allowed_list_ids, '[]'::jsonb)) > 0")


def downgrade() -> None:
    op.drop_column("actions", "scope_mode")
