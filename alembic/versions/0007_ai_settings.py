"""add persistent learning AI settings"""
from alembic import op
import sqlalchemy as sa

revision = "0007_ai_settings"
down_revision = "0006_learning_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider", sa.String(64), nullable=False, server_default="openai_compatible"),
        sa.Column("model", sa.String(255), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("base_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("ai_settings")
