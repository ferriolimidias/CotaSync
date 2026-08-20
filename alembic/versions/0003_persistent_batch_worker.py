"""add persistent batch worker state"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_persistent_batch_worker"
down_revision = "0002_run_origin"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("batches", sa.Column("worker_id", sa.String(128), nullable=True))
    op.add_column("batches", sa.Column("interrupted_items", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("batches", sa.Column("cancelled_items", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_batches_worker_id", "batches", ["worker_id"])
    op.create_index("ix_batches_status_created_at", "batches", ["status", "created_at"])

    op.create_table(
        "worker_instances",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("instance_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_batch_id", sa.String(128), sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("current_batch_item_id", sa.String(128), sa.ForeignKey("batch_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_worker_instances_instance_id", "worker_instances", ["instance_id"], unique=True)
    op.create_index("ix_worker_instances_status", "worker_instances", ["status"])
    op.create_index("ix_worker_instances_heartbeat_at", "worker_instances", ["heartbeat_at"])
    op.create_index("ix_worker_instances_current_batch_id", "worker_instances", ["current_batch_id"])
    op.create_index("ix_worker_instances_current_batch_item_id", "worker_instances", ["current_batch_item_id"])

    op.execute("update batches set status = 'queued' where status = 'pending'")
    op.execute("update batches set status = 'completed' where status = 'success'")
    op.execute("update batches set status = 'completed_with_errors' where status = 'partial_success'")
    op.execute("update batches set status = 'cancelled' where status = 'canceled'")
    op.execute("update batch_items set status = 'cancelled' where status = 'skipped'")
    op.execute(
        """
        update batches b
           set processed_items = s.processed_items,
               success_items = s.success_items,
               error_items = s.error_items,
               interrupted_items = s.interrupted_items,
               cancelled_items = s.cancelled_items
          from (
              select batch_id,
                     count(*) filter (where status in ('success','error','interrupted','cancelled')) as processed_items,
                     count(*) filter (where status = 'success') as success_items,
                     count(*) filter (where status = 'error') as error_items,
                     count(*) filter (where status = 'interrupted') as interrupted_items,
                     count(*) filter (where status = 'cancelled') as cancelled_items
                from batch_items
               group by batch_id
          ) s
         where b.id = s.batch_id
        """
    )


def downgrade():
    op.execute("update batch_items set status = 'skipped' where status = 'cancelled'")
    op.execute("update batches set status = 'pending' where status = 'queued'")
    op.execute("update batches set status = 'success' where status = 'completed'")
    op.execute("update batches set status = 'partial_success' where status = 'completed_with_errors'")
    op.execute("update batches set status = 'canceled' where status = 'cancelled'")
    op.drop_index("ix_worker_instances_current_batch_item_id", table_name="worker_instances")
    op.drop_index("ix_worker_instances_current_batch_id", table_name="worker_instances")
    op.drop_index("ix_worker_instances_heartbeat_at", table_name="worker_instances")
    op.drop_index("ix_worker_instances_status", table_name="worker_instances")
    op.drop_index("ix_worker_instances_instance_id", table_name="worker_instances")
    op.drop_table("worker_instances")
    op.drop_index("ix_batches_status_created_at", table_name="batches")
    op.drop_index("ix_batches_worker_id", table_name="batches")
    op.drop_column("batches", "cancelled_items")
    op.drop_column("batches", "interrupted_items")
    op.drop_column("batches", "worker_id")
