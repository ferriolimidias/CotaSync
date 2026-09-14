"""add worker-owned access cycle attention handshake metadata"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0027_access_cycle_attention"
down_revision = "0026_profile_identity_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_cycles", sa.Column("attention_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("access_cycles", sa.Column("attention_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("access_cycles", sa.Column("attention_reason", sa.String(length=128), nullable=True))
    op.add_column(
        "access_cycles",
        sa.Column("attention_details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("access_cycles", sa.Column("resume_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("access_cycles", "resume_requested_at")
    op.drop_column("access_cycles", "attention_details")
    op.drop_column("access_cycles", "attention_reason")
    op.drop_column("access_cycles", "attention_since")
    op.drop_column("access_cycles", "attention_requested_at")
