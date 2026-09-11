"""persist sanitized verified external identity evidence per profile"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0026_profile_identity_evidence"
down_revision = "0025_normalize_entry_urls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_access_profiles",
        sa.Column("identity_evidence", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("external_access_profiles", "identity_evidence")
