"""Persist encrypted Google Service Account settings per tenant."""
from alembic import op
import sqlalchemy as sa

revision = "0011_google_settings"
down_revision = "0010_action_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False, unique=True, index=True, server_default="default"),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("configured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connection_status", sa.String(length=32), nullable=False, server_default="not_configured"),
    )


def downgrade() -> None:
    op.drop_table("google_settings")
