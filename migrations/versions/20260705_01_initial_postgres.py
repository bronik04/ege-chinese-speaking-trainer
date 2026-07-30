"""Initial PostgreSQL schema for scale deployments."""

from alembic import op

# Схема перенесена сюда из удалённого trainer.infrastructure.database.postgres:
# ревизия опубликована и не может менять поведение, а модуль-источник больше
# не существует. Ветка исполняется только на PostgreSQL, поддержка которого
# снята (ADR 0004), поэтому фактически она мертва и оставлена ради целостности
# цепочки ревизий.
_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id BIGSERIAL PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 display_name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'student' CHECK(role IN ('student','teacher')),
 created_at BIGINT NOT NULL, email_verified_at BIGINT
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at BIGINT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_progress (
 user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, progress_json TEXT NOT NULL, updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS study_groups (
 id BIGSERIAL PRIMARY KEY, teacher_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name TEXT NOT NULL, join_code TEXT NOT NULL UNIQUE, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS group_members (
 group_id BIGINT NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
 user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, joined_at BIGINT NOT NULL,
 PRIMARY KEY(group_id,user_id)
);
CREATE TABLE IF NOT EXISTS assignments (
 id BIGSERIAL PRIMARY KEY, group_id BIGINT NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
 teacher_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL, variant_id TEXT NOT NULL,
 tasks_json TEXT NOT NULL, due_at BIGINT, created_at BIGINT NOT NULL, updated_at BIGINT,
 source_assignment_id BIGINT REFERENCES assignments(id), material_snapshot_json TEXT
);
CREATE TABLE IF NOT EXISTS submissions (
 id BIGSERIAL PRIMARY KEY, assignment_id BIGINT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
 student_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, attempt_number INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'submitted' CHECK(status IN ('submitted','graded')),
 run_json TEXT NOT NULL, submitted_at BIGINT NOT NULL, UNIQUE(assignment_id,student_id,attempt_number)
);
CREATE TABLE IF NOT EXISTS recordings (
 id BIGSERIAL PRIMARY KEY, submission_id BIGINT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
 task_number INTEGER NOT NULL CHECK(task_number BETWEEN 1 AND 3), question_number INTEGER, label TEXT NOT NULL,
 file_name TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, size_bytes BIGINT NOT NULL, created_at BIGINT NOT NULL,
 duration_seconds DOUBLE PRECISION, transcript_status TEXT NOT NULL DEFAULT 'disabled', transcript_text TEXT,
 transcript_error TEXT, transcribed_at BIGINT
);
CREATE TABLE IF NOT EXISTS reviews (
 submission_id BIGINT PRIMARY KEY REFERENCES submissions(id) ON DELETE CASCADE,
 teacher_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, scores_json TEXT NOT NULL,
 total_score INTEGER NOT NULL, max_score INTEGER NOT NULL, comment TEXT NOT NULL DEFAULT '', reviewed_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_tokens (
 token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('email_verification','password_reset')), expires_at BIGINT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_rate_limits (
 kind TEXT NOT NULL, subject_hash TEXT NOT NULL, attempts INTEGER NOT NULL, window_started_at BIGINT NOT NULL,
 blocked_until BIGINT NOT NULL DEFAULT 0, updated_at BIGINT NOT NULL, PRIMARY KEY(kind,subject_hash)
);
CREATE TABLE IF NOT EXISTS audit_log (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE SET NULL, email TEXT, action TEXT NOT NULL,
 ip_address TEXT NOT NULL DEFAULT '', user_agent TEXT NOT NULL DEFAULT '', details_json TEXT NOT NULL DEFAULT '{}', created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS transcription_jobs (
 id BIGSERIAL PRIMARY KEY, recording_id BIGINT NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','completed','failed')),
 attempts INTEGER NOT NULL DEFAULT 0, available_at BIGINT NOT NULL, locked_at BIGINT, last_error TEXT,
 created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
 id BIGSERIAL PRIMARY KEY, slug TEXT NOT NULL UNIQUE, owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('full','task')), task_number INTEGER CHECK(task_number BETWEEN 1 AND 3),
 title TEXT NOT NULL, year INTEGER NOT NULL, source TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','archived')),
 content_json TEXT NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL, published_at BIGINT
);
CREATE TABLE IF NOT EXISTS material_assets (
 id BIGSERIAL PRIMARY KEY, material_id BIGINT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
 storage_key TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, size_bytes BIGINT NOT NULL, created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS groups_teacher_idx ON study_groups(teacher_id);
CREATE INDEX IF NOT EXISTS members_user_idx ON group_members(user_id);
CREATE INDEX IF NOT EXISTS assignments_group_idx ON assignments(group_id,created_at);
CREATE INDEX IF NOT EXISTS submissions_assignment_idx ON submissions(assignment_id,submitted_at);
CREATE INDEX IF NOT EXISTS submissions_student_idx ON submissions(student_id,submitted_at);
CREATE INDEX IF NOT EXISTS recordings_submission_idx ON recordings(submission_id);
CREATE INDEX IF NOT EXISTS account_tokens_user_idx ON account_tokens(user_id,kind);
CREATE INDEX IF NOT EXISTS account_tokens_expiry_idx ON account_tokens(expires_at);
CREATE INDEX IF NOT EXISTS rate_limits_updated_idx ON auth_rate_limits(updated_at);
CREATE INDEX IF NOT EXISTS audit_user_idx ON audit_log(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS audit_email_idx ON audit_log(email,created_at DESC);
CREATE INDEX IF NOT EXISTS transcription_jobs_queue_idx ON transcription_jobs(status,available_at,id);
CREATE INDEX IF NOT EXISTS materials_owner_idx ON materials(owner_id,updated_at DESC);
CREATE INDEX IF NOT EXISTS materials_public_idx ON materials(status,year DESC);
CREATE INDEX IF NOT EXISTS material_assets_material_idx ON material_assets(material_id);
"""

revision = "20260705_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in _POSTGRES_SCHEMA.split(";"):
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
