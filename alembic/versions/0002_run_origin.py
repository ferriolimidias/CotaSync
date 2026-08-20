"""add run origin classification"""

from alembic import op
import sqlalchemy as sa


revision = "0002_run_origin"
down_revision = "0001_operational_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "runs",
        sa.Column("run_origin", sa.String(32), nullable=False, server_default="operational"),
    )
    op.create_check_constraint(
        "ck_runs_run_origin",
        "runs",
        "run_origin in ('operational', 'smoke', 'validation', 'automated_test', 'migration')",
    )
    op.create_index("ix_runs_run_origin", "runs", ["run_origin"])
    op.execute(
        """
        update runs
           set run_origin = case
               when created_at = timestamp with time zone '2026-08-20 12:52:15.29027+00'
                    then 'migration'
               when coalesce(diagnostics->'_record'->>'run_type', '') = 'validation_review'
                    then 'validation'
               when coalesce(diagnostics->'_record'->>'requested_by', '') ilike '%smoke%'
                    then 'smoke'
               when action_id is null
                    and coalesce(diagnostics->'_record'->>'run_type', '') = 'action_run'
                    then 'automated_test'
               when created_at >= timestamp with time zone '2026-08-20 13:40:00+00'
                    and coalesce(diagnostics->'_record'->>'run_type', '') = 'action_run'
                    then 'validation'
               else 'operational'
           end
        """
    )


def downgrade():
    op.drop_index("ix_runs_run_origin", table_name="runs")
    op.drop_constraint("ck_runs_run_origin", "runs", type_="check")
    op.drop_column("runs", "run_origin")
