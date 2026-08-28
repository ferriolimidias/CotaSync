"""add user auth version"""

from alembic import op
import sqlalchemy as sa


revision = "0005_user_auth_version"
down_revision = "0004_scoped_batch_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("auth_version", sa.Integer(), server_default="1", nullable=False))


def downgrade():
    op.drop_column("users", "auth_version")
