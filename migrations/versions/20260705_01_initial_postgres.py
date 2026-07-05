"""Initial PostgreSQL schema for scale deployments."""

from alembic import op

from backend.postgres import POSTGRES_SCHEMA

revision = "20260705_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in POSTGRES_SCHEMA.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    tables = [
        "transcription_jobs",
        "audit_log",
        "auth_rate_limits",
        "account_tokens",
        "reviews",
        "recordings",
        "submissions",
        "assignments",
        "group_members",
        "study_groups",
        "user_progress",
        "sessions",
        "users",
        "schema_migrations",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
