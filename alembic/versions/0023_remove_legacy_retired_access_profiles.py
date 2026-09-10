"""Remove access profiles left by the former retirement-only deletion flow."""

from alembic import op
import sqlalchemy as sa


revision = "0023_cleanup_retired_profiles"
down_revision = "0022_profile_delete_unlink"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Unlink and physically remove only unambiguous legacy retired profiles."""
    legacy = sa.text(
        """
        SELECT id
        FROM external_access_profiles
        WHERE active = false
          AND validation_status = 'retired'
          AND last_validation_reason = 'profile_retired'
        """
    )
    connection = op.get_bind()
    profile_ids = [row[0] for row in connection.execute(legacy)]
    if not profile_ids:
        return

    for profile_id in profile_ids:
        connection.execute(
            sa.text(
                """
                UPDATE action_versions
                SET definition = definition - 'required_access_profile_id'
                WHERE required_access_profile_id = :profile_id
                   OR definition->>'required_access_profile_id' = :profile_id
                """
            ),
            {"profile_id": profile_id},
        )

    for table, column in (
        ("client_lists", "access_profile_id"),
        ("actions", "required_access_profile_id"),
        ("action_versions", "required_access_profile_id"),
        ("runs", "access_profile_id"),
        ("batches", "access_profile_id"),
        ("learning_sessions", "access_profile_id"),
        ("access_cycles", "access_profile_id"),
    ):
        connection.execute(
            sa.text(f"UPDATE {table} SET {column} = NULL WHERE {column} = :profile_id"),
            [{"profile_id": profile_id} for profile_id in profile_ids],
        )

    connection.execute(
        sa.text(
            "DELETE FROM external_access_profiles WHERE id IN :profile_ids"
        ).bindparams(sa.bindparam("profile_ids", expanding=True)),
        {"profile_ids": profile_ids},
    )


def downgrade() -> None:
    # Deleted identities and credentials cannot be reconstructed safely.
    pass
