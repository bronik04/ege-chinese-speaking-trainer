"""Add expiring personal recordings and retention to review recordings."""

import sqlalchemy as sa
from alembic import op

from trainer.domain.recording_retention import expires_at

revision = "20260828_08"
down_revision = "20260819_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    identifier = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "personal_recordings",
        sa.Column("id", identifier, primary_key=True, autoincrement=True),
        sa.Column(
            "student_id",
            identifier,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("student_id", "run_id", "position"),
    )
    op.create_index(
        "personal_recordings_student_expiry_idx",
        "personal_recordings",
        ["student_id", sa.text("expires_at DESC")],
    )

    op.add_column("review_request_recordings", sa.Column("expires_at", sa.BigInteger(), nullable=True))
    connection = op.get_bind()
    recordings = connection.execute(sa.text("SELECT id, created_at FROM review_request_recordings")).mappings()
    for recording in recordings:
        connection.execute(
            sa.text("UPDATE review_request_recordings SET expires_at=:expires_at WHERE id=:id"),
            {"id": recording["id"], "expires_at": expires_at(recording["created_at"])},
        )
    with op.batch_alter_table("review_request_recordings") as batch:
        batch.alter_column("expires_at", existing_type=sa.BigInteger(), nullable=False)
    op.create_index("review_request_recordings_expiry_idx", "review_request_recordings", ["expires_at"])


def downgrade() -> None:
    op.drop_index("review_request_recordings_expiry_idx", table_name="review_request_recordings")
    with op.batch_alter_table("review_request_recordings") as batch:
        batch.drop_column("expires_at")
    op.drop_index("personal_recordings_student_expiry_idx", table_name="personal_recordings")
    op.drop_table("personal_recordings")
