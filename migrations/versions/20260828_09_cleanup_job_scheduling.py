"""Schedule storage cleanup jobs without racing active uploads."""

import sqlalchemy as sa
from alembic import op

revision = "20260828_09"
down_revision = "20260828_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("storage_cleanup_jobs", sa.Column("available_at", sa.BigInteger(), nullable=True))
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE storage_cleanup_jobs SET available_at=created_at"))
    with op.batch_alter_table("storage_cleanup_jobs") as batch:
        batch.alter_column("available_at", existing_type=sa.BigInteger(), nullable=False)
    op.create_index("storage_cleanup_jobs_available_idx", "storage_cleanup_jobs", ["available_at", "id"])


def downgrade() -> None:
    op.drop_index("storage_cleanup_jobs_available_idx", table_name="storage_cleanup_jobs")
    with op.batch_alter_table("storage_cleanup_jobs") as batch:
        batch.drop_column("available_at")
