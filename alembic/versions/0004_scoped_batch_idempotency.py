"""scope batch idempotency by user and request fingerprint"""

from alembic import op
import sqlalchemy as sa


revision = "0004_scoped_batch_idempotency"
down_revision = "0003_persistent_batch_worker"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("batches", sa.Column("idempotency_user_id", sa.String(255), nullable=True))
    op.add_column("batches", sa.Column("idempotency_operation", sa.String(64), nullable=True))
    op.add_column("batches", sa.Column("idempotency_fingerprint", sa.String(128), nullable=True))
    op.execute(
        """
        update batches
           set idempotency_user_id = coalesce(nullif(created_by, ''), 'legacy'),
               idempotency_operation = 'batch:create',
               idempotency_fingerprint = 'legacy:' || id
         where idempotency_key is not null
        """
    )
    op.drop_constraint("batches_idempotency_key_key", "batches", type_="unique")
    op.create_index("ix_batches_idempotency_user_id", "batches", ["idempotency_user_id"])
    op.create_index("ix_batches_idempotency_operation", "batches", ["idempotency_operation"])
    op.create_unique_constraint(
        "uq_batches_idempotency_scope",
        "batches",
        ["idempotency_user_id", "idempotency_operation", "idempotency_key"],
    )


def downgrade():
    op.drop_constraint("uq_batches_idempotency_scope", "batches", type_="unique")
    op.drop_index("ix_batches_idempotency_operation", table_name="batches")
    op.drop_index("ix_batches_idempotency_user_id", table_name="batches")
    op.create_unique_constraint("batches_idempotency_key_key", "batches", ["idempotency_key"])
    op.drop_column("batches", "idempotency_fingerprint")
    op.drop_column("batches", "idempotency_operation")
    op.drop_column("batches", "idempotency_user_id")
