"""Store the canonical ExternalSystem entry URL on access cycles."""

from alembic import op
import sqlalchemy as sa

revision = "0019_access_cycle_entry_url"
down_revision = "0018_access_cycles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_cycles", sa.Column("entry_url", sa.Text(), nullable=True))
    op.execute(
        "UPDATE access_cycles c SET entry_url = COALESCE(e.config->>'entry_url', e.config->>'external_login_url', '') "
        "FROM external_systems e WHERE e.id = c.external_system_id"
    )
    op.alter_column("access_cycles", "entry_url", nullable=False)


def downgrade() -> None:
    op.drop_column("access_cycles", "entry_url")
