"""Add isolated durable storage for voluntary review requests."""

import sqlalchemy as sa
from alembic import op

revision = "20260819_07"
down_revision = "20260818_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("variant_id", sa.Text(), nullable=False),
        sa.Column("run_json", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.Integer(), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("kind IN ('task', 'attempt')", name="review_requests_kind_check"),
        sa.CheckConstraint("status IN ('uploading', 'queued', 'reviewed')", name="review_requests_status_check"),
    )
    op.create_index(
        "review_requests_student_submitted_idx", "review_requests", ["student_id", sa.text("submitted_at DESC")]
    )
    op.create_index("review_requests_queue_idx", "review_requests", ["status", sa.text("submitted_at ASC")])

    op.create_table(
        "review_request_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("review_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_number", sa.Integer(), nullable=False),
        sa.Column("task_snapshot_json", sa.Text(), nullable=False),
        sa.Column("scores_json", sa.Text(), nullable=True),
        sa.Column("total_score", sa.Integer(), nullable=True),
        sa.Column("max_score", sa.Integer(), nullable=True),
        sa.CheckConstraint("task_number BETWEEN 1 AND 3", name="review_request_items_task_number_check"),
        sa.UniqueConstraint("request_id", "task_number"),
    )
    op.create_index("review_request_items_request_idx", "review_request_items", ["request_id"])

    op.create_table(
        "review_request_recordings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_id", sa.Integer(), sa.ForeignKey("review_request_items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("question_number", sa.Integer(), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint("item_id", "question_number"),
    )
    op.create_index("review_request_recordings_item_idx", "review_request_recordings", ["item_id"])
    op.create_index(
        "review_request_recordings_item_question_idx",
        "review_request_recordings",
        ["item_id", "question_number"],
        unique=True,
        sqlite_where=sa.text("question_number IS NOT NULL"),
        postgresql_where=sa.text("question_number IS NOT NULL"),
    )
    op.create_index(
        "review_request_recordings_item_unanswered_idx",
        "review_request_recordings",
        ["item_id"],
        unique=True,
        sqlite_where=sa.text("question_number IS NULL"),
        postgresql_where=sa.text("question_number IS NULL"),
    )

    op.create_table(
        "review_request_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("review_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
    )
    op.create_index("review_request_assets_request_idx", "review_request_assets", ["request_id"])


def downgrade() -> None:
    op.drop_index("review_request_assets_request_idx", table_name="review_request_assets")
    op.drop_table("review_request_assets")
    op.drop_index("review_request_recordings_item_unanswered_idx", table_name="review_request_recordings")
    op.drop_index("review_request_recordings_item_question_idx", table_name="review_request_recordings")
    op.drop_index("review_request_recordings_item_idx", table_name="review_request_recordings")
    op.drop_table("review_request_recordings")
    op.drop_index("review_request_items_request_idx", table_name="review_request_items")
    op.drop_table("review_request_items")
    op.drop_index("review_requests_queue_idx", table_name="review_requests")
    op.drop_index("review_requests_student_submitted_idx", table_name="review_requests")
    op.drop_table("review_requests")
