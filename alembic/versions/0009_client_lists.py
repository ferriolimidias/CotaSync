"""Add stable client lists and action list scopes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009_client_lists"
down_revision = "0008_system_spreadsheets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_lists",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_client_lists_tenant_id", "client_lists", ["tenant_id"])
    op.add_column("clients", sa.Column("list_id", sa.String(128), nullable=True))
    op.create_index("ix_clients_list_id", "clients", ["list_id"])
    op.create_foreign_key("fk_clients_list_id", "clients", "client_lists", ["list_id"], ["id"], ondelete="SET NULL")
    op.add_column("actions", sa.Column("allowed_list_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.execute("""
        INSERT INTO client_lists (id, tenant_id, name)
        SELECT 'list-' || md5(coalesce(client_group, 'Lista Principal')), 'default', coalesce(nullif(client_group, ''), 'Lista Principal')
        FROM clients
        WHERE coalesce(client_group, '') <> ''
        GROUP BY client_group
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
        UPDATE clients
        SET list_id = 'list-' || md5(coalesce(client_group, 'Lista Principal'))
        WHERE coalesce(client_group, '') <> ''
    """)


def downgrade() -> None:
    op.drop_column("actions", "allowed_list_ids")
    op.drop_constraint("fk_clients_list_id", "clients", type_="foreignkey")
    op.drop_index("ix_clients_list_id", table_name="clients")
    op.drop_column("clients", "list_id")
    op.drop_index("ix_client_lists_tenant_id", table_name="client_lists")
    op.drop_table("client_lists")
