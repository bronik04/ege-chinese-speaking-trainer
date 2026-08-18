from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from trainer.infrastructure.database.migrations import (
    apply_sqlite_baseline,
    head_revision,
    upgrade_sqlite_database,
)

EXPECTED_TABLES = {
    "account_tokens",
    "assignment_material_assets",
    "assignments",
    "audit_log",
    "auth_rate_limits",
    "group_members",
    "material_assets",
    "materials",
    "recordings",
    "reviews",
    "sessions",
    "storage_cleanup_jobs",
    "study_groups",
    "submissions",
    "user_progress",
    "users",
}


def sqlite_schema(path: Path) -> tuple[set[str], set[str]]:
    with closing(sqlite3.connect(path)) as database:
        tables = {
            row[0]
            for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("sqlite_") and row[0] not in {"alembic_version", "schema_migrations"}
        }
        indexes = {
            row[0]
            for row in database.execute("SELECT name FROM sqlite_master WHERE type='index'")
            if not row[0].startswith("sqlite_autoindex_")
        }
    return tables, indexes


class SqliteMigrationTest(unittest.TestCase):
    def test_legacy_baseline_rejects_new_sqlite_migration(self):
        from trainer.infrastructure.database import migrations

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                extended = [*migrations.MIGRATIONS, (8, lambda connection: None)]
                with patch.object(migrations, "MIGRATIONS", extended):
                    with self.assertRaisesRegex(RuntimeError, "frozen"):
                        apply_sqlite_baseline(database)

    def test_clean_database_gets_baseline_and_alembic_head(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                versions = [
                    row[0] for row in database.execute("SELECT version FROM schema_migrations ORDER BY version")
                ]
                revision = database.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                assignment_asset_columns = {
                    row[1] for row in database.execute("PRAGMA table_info(assignment_material_assets)")
                }
                cleanup_columns = {row[1] for row in database.execute("PRAGMA table_info(storage_cleanup_jobs)")}
            self.assertEqual(versions, list(range(1, 8)))
            self.assertEqual(revision, head_revision())
            self.assertEqual(sqlite_schema(path)[0], EXPECTED_TABLES)
            self.assertEqual(
                assignment_asset_columns,
                {"id", "assignment_id", "storage_key", "mime_type", "size_bytes", "created_at"},
            )
            self.assertIn("assignment_material_assets_assignment_idx", sqlite_schema(path)[1])
            self.assertEqual(
                cleanup_columns,
                {
                    "id",
                    "audio_keys_json",
                    "material_keys_json",
                    "assignment_keys_json",
                    "attempts",
                    "last_error",
                    "created_at",
                    "updated_at",
                },
            )
            self.assertIn("storage_cleanup_jobs_created_idx", sqlite_schema(path)[1])

    def test_existing_legacy_database_is_stamped_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                with database:
                    apply_sqlite_baseline(database)
                    database.execute(
                        "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                        ("kept@example.test", "hash", "Kept", "student", 1),
                    )
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                email = database.execute("SELECT email FROM users").fetchone()[0]
                revision = database.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            self.assertEqual(email, "kept@example.test")
            self.assertEqual(revision, head_revision())

    def test_repeated_upgrade_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            before = sqlite_schema(path)
            upgrade_sqlite_database(path)
            self.assertEqual(sqlite_schema(path), before)

    def test_head_removes_transcription_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.db"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                columns = {row[1] for row in database.execute("PRAGMA table_info(recordings)")}
        self.assertNotIn("transcription_jobs", tables)
        self.assertFalse({"transcript_status", "transcript_text", "transcript_error", "transcribed_at"} & columns)

    def test_head_allows_uploading_submission_without_submitted_at(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                database.execute(
                    """
                    INSERT INTO submissions(assignment_id, student_id, attempt_number, status, run_json, submitted_at)
                    VALUES (1, 1, 1, 'uploading', '{}', NULL)
                    """
                )
                status, submitted_at = database.execute(
                    "SELECT status, submitted_at FROM submissions WHERE id = 1"
                ).fetchone()
        self.assertEqual(status, "uploading")
        self.assertIsNone(submitted_at)


if __name__ == "__main__":
    unittest.main()
