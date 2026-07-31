"""Drop transcription queue and recording transcript columns."""

import sqlalchemy as sa
from alembic import op

revision = "20260730_05"
down_revision = "20260712_04"
branch_labels = None
depends_on = None

TRANSCRIPT_COLUMNS = ("transcript_status", "transcript_text", "transcript_error", "transcribed_at")


def _recordings_table(metadata: sa.MetaData, *, with_transcript_columns: bool) -> sa.Table:
    # SQLAlchemy reflection on SQLite does not carry ON DELETE CASCADE into
    # batch_alter_table's automatic reflection, so a plain drop_column() call
    # would silently downgrade this foreign key to NO ACTION and break
    # cascading account deletion. Declaring the table explicitly keeps the
    # constraint intact across the SQLite copy-and-swap that batch mode does
    # for column drops.
    columns = [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_number", sa.Integer(), nullable=False),
        sa.Column("question_number", sa.Integer()),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False, unique=True),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float()),
    ]
    if with_transcript_columns:
        columns += [
            sa.Column("transcript_status", sa.Text(), nullable=False, server_default="disabled"),
            sa.Column("transcript_text", sa.Text()),
            sa.Column("transcript_error", sa.Text()),
            sa.Column("transcribed_at", sa.Integer()),
        ]
    return sa.Table(
        "recordings",
        metadata,
        *columns,
        sa.CheckConstraint("task_number BETWEEN 1 AND 3"),
    )


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS transcription_jobs_queue_idx")
    op.execute("DROP TABLE IF EXISTS transcription_jobs")
    current = _recordings_table(sa.MetaData(), with_transcript_columns=True)
    with op.batch_alter_table("recordings", copy_from=current) as batch:
        for name in TRANSCRIPT_COLUMNS:
            batch.drop_column(name)


def downgrade() -> None:
    current = _recordings_table(sa.MetaData(), with_transcript_columns=False)
    with op.batch_alter_table("recordings", copy_from=current) as batch:
        batch.add_column(sa.Column("transcript_status", sa.Text(), nullable=False, server_default="disabled"))
        batch.add_column(sa.Column("transcript_text", sa.Text()))
        batch.add_column(sa.Column("transcript_error", sa.Text()))
        batch.add_column(sa.Column("transcribed_at", sa.Integer()))
    op.create_table(
        "transcription_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "recording_id",
            sa.Integer(),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
    )
    op.create_index("transcription_jobs_queue_idx", "transcription_jobs", ["status", "available_at", "id"])
