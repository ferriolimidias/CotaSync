"""Allow real access-profile deletion without deleting access-cycle history."""

from alembic import op
import sqlalchemy as sa


revision = "0022_profile_delete_unlink"
down_revision = "0021_learning_access_cycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("access_cycles_access_profile_id_fkey", "access_cycles", type_="foreignkey")
    op.alter_column("access_cycles", "access_profile_id", existing_type=sa.String(128), nullable=True)
    op.create_foreign_key(
        "access_cycles_access_profile_id_fkey",
        "access_cycles",
        "external_access_profiles",
        ["access_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("access_cycles_access_profile_id_fkey", "access_cycles", type_="foreignkey")
    op.execute(sa.text("DELETE FROM access_cycles WHERE access_profile_id IS NULL"))
    op.alter_column("access_cycles", "access_profile_id", existing_type=sa.String(128), nullable=False)
    op.create_foreign_key(
        "access_cycles_access_profile_id_fkey",
        "access_cycles",
        "external_access_profiles",
        ["access_profile_id"],
        ["id"],
        ondelete="CASCADE",
    )
