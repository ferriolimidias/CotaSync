"""Add tenant-scoped external access profiles and immutable run context."""

from alembic import op
import sqlalchemy as sa


revision = "0014_access_profiles"
down_revision = "0013_batch_attempt_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_access_profiles",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
        sa.Column("external_system_id", sa.String(128), sa.ForeignKey("external_systems.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("login_identifier", sa.String(255), nullable=False),
        sa.Column("external_code", sa.String(255)),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "external_system_id", "login_identifier", name="uq_access_profile_login"),
    )
    op.create_index("ix_external_access_profiles_tenant_id", "external_access_profiles", ["tenant_id"])
    op.create_index("ix_external_access_profiles_external_system_id", "external_access_profiles", ["external_system_id"])

    op.add_column("client_lists", sa.Column("access_profile_id", sa.String(128), nullable=True))
    op.create_foreign_key("fk_client_lists_access_profile", "client_lists", "external_access_profiles", ["access_profile_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_client_lists_access_profile_id", "client_lists", ["access_profile_id"])

    op.add_column("actions", sa.Column("required_access_profile_id", sa.String(128), nullable=True))
    op.create_foreign_key("fk_actions_access_profile", "actions", "external_access_profiles", ["required_access_profile_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_actions_required_access_profile_id", "actions", ["required_access_profile_id"])

    op.add_column("action_versions", sa.Column("required_access_profile_id", sa.String(128), nullable=True))
    op.add_column("action_versions", sa.Column("run_start_strategy", sa.String(64), nullable=False, server_default="persistent_graph_reentry"))
    op.create_foreign_key("fk_action_versions_access_profile", "action_versions", "external_access_profiles", ["required_access_profile_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_action_versions_required_access_profile_id", "action_versions", ["required_access_profile_id"])

    op.add_column("runs", sa.Column("access_profile_id", sa.String(128), nullable=True))
    op.add_column("runs", sa.Column("external_system_id", sa.String(128), nullable=True))
    op.add_column("runs", sa.Column("run_start_strategy", sa.String(64), nullable=True))
    op.create_foreign_key("fk_runs_access_profile", "runs", "external_access_profiles", ["access_profile_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_runs_external_system", "runs", "external_systems", ["external_system_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_runs_access_profile_id", "runs", ["access_profile_id"])
    op.create_index("ix_runs_external_system_id", "runs", ["external_system_id"])

    op.add_column("batches", sa.Column("access_profile_id", sa.String(128), nullable=True))
    op.add_column("batches", sa.Column("external_system_id", sa.String(128), nullable=True))
    op.add_column("batches", sa.Column("run_start_strategy", sa.String(64), nullable=True))
    op.create_foreign_key("fk_batches_access_profile", "batches", "external_access_profiles", ["access_profile_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_batches_external_system", "batches", "external_systems", ["external_system_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_batches_access_profile_id", "batches", ["access_profile_id"])
    op.create_index("ix_batches_external_system_id", "batches", ["external_system_id"])


def downgrade() -> None:
    for name, table in (
        ("ix_batches_external_system_id", "batches"),
        ("ix_batches_access_profile_id", "batches"),
        ("ix_runs_external_system_id", "runs"),
        ("ix_runs_access_profile_id", "runs"),
        ("ix_action_versions_required_access_profile_id", "action_versions"),
        ("ix_actions_required_access_profile_id", "actions"),
        ("ix_client_lists_access_profile_id", "client_lists"),
        ("ix_external_access_profiles_external_system_id", "external_access_profiles"),
        ("ix_external_access_profiles_tenant_id", "external_access_profiles"),
    ):
        op.drop_index(name, table_name=table)
    for name, table in (
        ("fk_batches_external_system", "batches"),
        ("fk_batches_access_profile", "batches"),
        ("fk_runs_external_system", "runs"),
        ("fk_runs_access_profile", "runs"),
        ("fk_action_versions_access_profile", "action_versions"),
        ("fk_actions_access_profile", "actions"),
        ("fk_client_lists_access_profile", "client_lists"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")
    for column, table in (
        ("run_start_strategy", "batches"), ("external_system_id", "batches"), ("access_profile_id", "batches"),
        ("run_start_strategy", "runs"), ("external_system_id", "runs"), ("access_profile_id", "runs"),
        ("run_start_strategy", "action_versions"), ("required_access_profile_id", "action_versions"),
        ("required_access_profile_id", "actions"), ("access_profile_id", "client_lists"),
    ):
        op.drop_column(table, column)
    op.drop_table("external_access_profiles")
