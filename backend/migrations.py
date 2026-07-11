from __future__ import annotations

import sqlite3


def migration_001_core(database: sqlite3.Connection) -> None:
    database.executescript(
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'student' CHECK(role IN ('student', 'teacher')),
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            progress_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS study_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            join_code TEXT NOT NULL UNIQUE,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            joined_at INTEGER NOT NULL,
            PRIMARY KEY(group_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
        CREATE INDEX IF NOT EXISTS groups_teacher_idx ON study_groups(teacher_id);
        CREATE INDEX IF NOT EXISTS members_user_idx ON group_members(user_id);
        """
    )
    columns = {row["name"] for row in database.execute("PRAGMA table_info(users)")}
    if "display_name" not in columns:
        database.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
    if "role" not in columns:
        database.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'")


def migration_002_assignments_and_reviews(database: sqlite3.Connection) -> None:
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
            teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            variant_id TEXT NOT NULL,
            tasks_json TEXT NOT NULL,
            due_at INTEGER,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            attempt_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'submitted' CHECK(status IN ('submitted', 'graded')),
            run_json TEXT NOT NULL,
            submitted_at INTEGER NOT NULL,
            UNIQUE(assignment_id, student_id, attempt_number)
        );
        CREATE TABLE IF NOT EXISTS recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            task_number INTEGER NOT NULL CHECK(task_number BETWEEN 1 AND 3),
            question_number INTEGER,
            label TEXT NOT NULL,
            file_name TEXT NOT NULL UNIQUE,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            submission_id INTEGER PRIMARY KEY REFERENCES submissions(id) ON DELETE CASCADE,
            teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            scores_json TEXT NOT NULL,
            total_score INTEGER NOT NULL,
            max_score INTEGER NOT NULL,
            comment TEXT NOT NULL DEFAULT '',
            reviewed_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS assignments_group_idx ON assignments(group_id, created_at);
        CREATE INDEX IF NOT EXISTS submissions_assignment_idx ON submissions(assignment_id, submitted_at);
        CREATE INDEX IF NOT EXISTS submissions_student_idx ON submissions(student_id, submitted_at);
        CREATE INDEX IF NOT EXISTS recordings_submission_idx ON recordings(submission_id);
        """
    )


def migration_003_account_security(database: sqlite3.Connection) -> None:
    columns = {row["name"] for row in database.execute("PRAGMA table_info(users)")}
    if "email_verified_at" not in columns:
        database.execute("ALTER TABLE users ADD COLUMN email_verified_at INTEGER")
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS account_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('email_verification', 'password_reset')),
            expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_rate_limits (
            kind TEXT NOT NULL,
            subject_hash TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            window_started_at INTEGER NOT NULL,
            blocked_until INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY(kind, subject_hash)
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            email TEXT,
            action TEXT NOT NULL,
            ip_address TEXT NOT NULL DEFAULT '',
            user_agent TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS account_tokens_user_idx ON account_tokens(user_id, kind);
        CREATE INDEX IF NOT EXISTS account_tokens_expiry_idx ON account_tokens(expires_at);
        CREATE INDEX IF NOT EXISTS rate_limits_updated_idx ON auth_rate_limits(updated_at);
        CREATE INDEX IF NOT EXISTS audit_user_idx ON audit_log(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS audit_email_idx ON audit_log(email, created_at DESC);
        """
    )


def migration_004_assignment_delivery(database: sqlite3.Connection) -> None:
    columns = {row["name"] for row in database.execute("PRAGMA table_info(assignments)")}
    if "updated_at" not in columns:
        database.execute("ALTER TABLE assignments ADD COLUMN updated_at INTEGER")
    if "source_assignment_id" not in columns:
        database.execute("ALTER TABLE assignments ADD COLUMN source_assignment_id INTEGER REFERENCES assignments(id)")
    recording_columns = {row["name"] for row in database.execute("PRAGMA table_info(recordings)")}
    if "duration_seconds" not in recording_columns:
        database.execute("ALTER TABLE recordings ADD COLUMN duration_seconds REAL")


def migration_005_transcriptions(database: sqlite3.Connection) -> None:
    columns = {row["name"] for row in database.execute("PRAGMA table_info(recordings)")}
    additions = {
        "transcript_status": "TEXT NOT NULL DEFAULT 'disabled'",
        "transcript_text": "TEXT",
        "transcript_error": "TEXT",
        "transcribed_at": "INTEGER",
    }
    for name, definition in additions.items():
        if name not in columns:
            database.execute(f"ALTER TABLE recordings ADD COLUMN {name} {definition}")
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS transcription_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id INTEGER NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at INTEGER NOT NULL,
            locked_at INTEGER,
            last_error TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS transcription_jobs_queue_idx
            ON transcription_jobs(status, available_at, id);
        """
    )


def migration_006_materials(database: sqlite3.Connection) -> None:
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('full', 'task')),
            task_number INTEGER CHECK(task_number BETWEEN 1 AND 3),
            title TEXT NOT NULL,
            year INTEGER NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'published', 'archived')),
            content_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            published_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS material_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
            storage_key TEXT NOT NULL UNIQUE,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS materials_owner_idx ON materials(owner_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS materials_public_idx ON materials(status, year DESC);
        CREATE INDEX IF NOT EXISTS material_assets_material_idx ON material_assets(material_id);
        """
    )


def migration_007_assignment_material_snapshots(database: sqlite3.Connection) -> None:
    columns = {row["name"] for row in database.execute("PRAGMA table_info(assignments)")}
    if "material_snapshot_json" not in columns:
        database.execute("ALTER TABLE assignments ADD COLUMN material_snapshot_json TEXT")


MIGRATIONS = [
    (1, migration_001_core),
    (2, migration_002_assignments_and_reviews),
    (3, migration_003_account_security),
    (4, migration_004_assignment_delivery),
    (5, migration_005_transcriptions),
    (6, migration_006_materials),
    (7, migration_007_assignment_material_snapshots),
]


def apply_migrations(database: sqlite3.Connection) -> None:
    database.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL DEFAULT (unixepoch()))"
    )
    applied = {row["version"] for row in database.execute("SELECT version FROM schema_migrations")}
    for version, migration in MIGRATIONS:
        if version in applied:
            continue
        migration(database)
        database.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
