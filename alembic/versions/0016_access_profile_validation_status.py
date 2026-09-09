"""Persist the last safe validation result for access profiles."""

from alembic import op
import sqlalchemy as sa


revision = "0016_access_profile_validation"
down_revision = "0015_durable_learning_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_access_profiles",
        sa.Column("validation_status", sa.String(32), nullable=False, server_default="unverified"),
    )
    op.add_column("external_access_profiles", sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("external_access_profiles", sa.Column("last_validation_reason", sa.String(255), nullable=True))
    op.create_index("ix_external_access_profiles_validation_status", "external_access_profiles", ["validation_status"])


def downgrade() -> None:
    op.drop_index("ix_external_access_profiles_validation_status", table_name="external_access_profiles")
    op.drop_column("external_access_profiles", "last_validation_reason")
    op.drop_column("external_access_profiles", "last_validated_at")
    op.drop_column("external_access_profiles", "validation_status")
