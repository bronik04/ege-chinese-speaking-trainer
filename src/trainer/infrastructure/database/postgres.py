from __future__ import annotations

import os
import re
import threading

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

IDENTITY_TABLES = {
    "users",
    "study_groups",
    "assignments",
    "submissions",
    "recordings",
    "audit_log",
    "transcription_jobs",
    "materials",
    "material_assets",
}
_POOLS: dict[str, ConnectionPool] = {}
_POOL_LOCK = threading.Lock()


def _pool(url: str) -> ConnectionPool:
    with _POOL_LOCK:
        if url not in _POOLS:
            _POOLS[url] = ConnectionPool(
                conninfo=url,
                min_size=int(os.environ.get("TRAINER_DB_POOL_MIN", "1")),
                max_size=int(os.environ.get("TRAINER_DB_POOL_MAX", "10")),
                kwargs={"row_factory": dict_row},
                open=True,
            )
        return _POOLS[url]


class Cursor:
    def __init__(self, cursor, *, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)


class Connection:
    def __init__(self, url: str):
        self._pool = _pool(url)
        self._connection = self._pool.getconn()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type:
                self._connection.rollback()
            else:
                self._connection.commit()
        finally:
            self._pool.putconn(self._connection)

    @staticmethod
    def _translate(sql: str) -> str:
        translated = sql.replace("?", "%s")
        match = re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\s+([a-z_]+)", translated, re.IGNORECASE)
        if match:
            translated = re.sub(r"INSERT\s+OR\s+IGNORE", "INSERT", translated, count=1, flags=re.IGNORECASE)
            translated = translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return translated

    def execute(self, sql: str, parameters=()) -> Cursor:
        translated = self._translate(sql)
        insert = re.match(r"\s*INSERT\s+INTO\s+([a-z_]+)", translated, re.IGNORECASE)
        wants_id = bool(insert and insert.group(1).lower() in IDENTITY_TABLES and "RETURNING" not in translated.upper())
        if wants_id:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"
        cursor = self._connection.execute(translated, tuple(parameters))
        lastrowid = cursor.fetchone()["id"] if wants_id else None
        return Cursor(cursor, lastrowid=lastrowid)


def connect(url: str) -> Connection:
    return Connection(url)


def close_pools() -> None:
    with _POOL_LOCK:
        for pool in _POOLS.values():
            pool.close()
        _POOLS.clear()


# Frozen PostgreSQL baseline used only by the published 20260705_01 Alembic revision.
# New schema changes belong in new, cross-dialect Alembic revisions.
POSTGRES_SCHEMA = """
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


def initialize(url: str) -> None:
    from trainer.infrastructure.database.migrations import upgrade_database

    upgrade_database(url)
