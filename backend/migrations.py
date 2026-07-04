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


MIGRATIONS = [(1, migration_001_core), (2, migration_002_assignments_and_reviews)]


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
