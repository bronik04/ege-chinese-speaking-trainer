"""Add the uploading submission state."""

import sqlalchemy as sa
from alembic import op

revision = "20260818_06"
down_revision = "20260730_05"
branch_labels = None
depends_on = None


def _submissions_table(metadata: sa.MetaData, statuses: tuple[str, ...], submitted_at_nullable: bool) -> sa.Table:
    allowed_statuses = ", ".join(repr(status) for status in statuses)
    return sa.Table(
        "submissions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="submitted"),
        sa.Column("run_json", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.Integer(), nullable=submitted_at_nullable),
        sa.CheckConstraint(f"status IN ({allowed_statuses})", name="submissions_status_check"),
        sa.UniqueConstraint("assignment_id", "student_id", "attempt_number"),
    )


def upgrade() -> None:
    current = _submissions_table(sa.MetaData(), ("submitted", "graded"), submitted_at_nullable=False)
    with op.batch_alter_table("submissions", recreate="always", copy_from=current) as batch:
        batch.drop_constraint("submissions_status_check", type_="check")
        batch.create_check_constraint("submissions_status_check", "status IN ('uploading', 'submitted', 'graded')")
        batch.alter_column("submitted_at", existing_type=sa.Integer(), nullable=True)
    op.create_table(
        "storage_cleanup_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("audio_keys_json", sa.Text(), nullable=False),
        sa.Column("material_keys_json", sa.Text(), nullable=False),
        sa.Column("assignment_keys_json", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
    )
    op.create_index("storage_cleanup_jobs_created_idx", "storage_cleanup_jobs", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("storage_cleanup_jobs_created_idx", table_name="storage_cleanup_jobs")
    op.drop_table("storage_cleanup_jobs")
    current = _submissions_table(sa.MetaData(), ("uploading", "submitted", "graded"), submitted_at_nullable=True)
    with op.batch_alter_table("submissions", recreate="always", copy_from=current) as batch:
        batch.drop_constraint("submissions_status_check", type_="check")
        batch.create_check_constraint("submissions_status_check", "status IN ('submitted', 'graded')")
        batch.alter_column("submitted_at", existing_type=sa.Integer(), nullable=False)
