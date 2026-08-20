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
    "review_request_assets",
    "review_request_items",
    "review_request_recordings",
    "review_requests",
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
            self.assertTrue(
                {
                    "review_requests_student_submitted_idx",
                    "review_requests_queue_idx",
                    "review_request_items_request_idx",
                    "review_request_recordings_item_idx",
                    "review_request_recordings_item_question_idx",
                    "review_request_recordings_item_unanswered_idx",
                    "review_request_assets_request_idx",
                }.issubset(sqlite_schema(path)[1])
            )

    def test_review_recording_allows_one_unquestioned_recording_per_item(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                database.execute("PRAGMA foreign_keys=ON")
                student_id = database.execute(
                    "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                    ("student@example.test", "hash", "Student", "student", 1),
                ).lastrowid
                request_id = database.execute(
                    """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json)
                       VALUES (?,?,?,?,?)""",
                    (student_id, "task", "uploading", "demo-2026", "{}"),
                ).lastrowid
                item_id = database.execute(
                    """INSERT INTO review_request_items(request_id,task_number,task_snapshot_json)
                       VALUES (?,?,?)""",
                    (request_id, 2, "{}"),
                ).lastrowid
                database.execute(
                    """INSERT INTO review_request_recordings(item_id,question_number,label,storage_key,mime_type,size_bytes,created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (item_id, None, "First", "private/first.webm", "audio/webm", 1, 1),
                )

                with self.assertRaises(sqlite3.IntegrityError):
                    database.execute(
                        """INSERT INTO review_request_recordings(item_id,question_number,label,storage_key,mime_type,size_bytes,created_at)
                           VALUES (?,?,?,?,?,?,?)""",
                        (item_id, None, "Second", "private/second.webm", "audio/webm", 1, 1),
                    )

    def test_existing_legacy_rows_are_retained_when_review_queue_is_added(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                with database:
                    apply_sqlite_baseline(database)
                    teacher_id = database.execute(
                        "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                        ("teacher@example.test", "hash", "Teacher", "teacher", 1),
                    ).lastrowid
                    student_id = database.execute(
                        "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                        ("student@example.test", "hash", "Student", "student", 1),
                    ).lastrowid
                    group_id = database.execute(
                        "INSERT INTO study_groups(teacher_id,name,join_code,created_at) VALUES (?,?,?,?)",
                        (teacher_id, "Legacy group", "LEGACY", 2),
                    ).lastrowid
                    database.execute(
                        "INSERT INTO group_members(group_id,user_id,joined_at) VALUES (?,?,?)",
                        (group_id, student_id, 3),
                    )
                    assignment_id = database.execute(
                        """INSERT INTO assignments(
                               group_id,teacher_id,title,variant_id,tasks_json,due_at,created_at,
                               updated_at,source_assignment_id,material_snapshot_json
                           ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (group_id, teacher_id, "Legacy assignment", "open-2026", "[1]", 10, 4, 4, None, "{}"),
                    ).lastrowid
                    submission_id = database.execute(
                        """INSERT INTO submissions(
                               assignment_id,student_id,attempt_number,status,run_json,submitted_at
                           ) VALUES (?,?,?,?,?,?)""",
                        (assignment_id, student_id, 1, "submitted", '{"id":"legacy-run"}', 5),
                    ).lastrowid
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                group = database.execute(
                    "SELECT teacher_id,name,join_code FROM study_groups WHERE id=?", (group_id,)
                ).fetchone()
                member = database.execute(
                    "SELECT group_id,user_id,joined_at FROM group_members WHERE group_id=? AND user_id=?",
                    (group_id, student_id),
                ).fetchone()
                assignment = database.execute(
                    "SELECT group_id,teacher_id,title,variant_id,tasks_json FROM assignments WHERE id=?",
                    (assignment_id,),
                ).fetchone()
                submission = database.execute(
                    "SELECT assignment_id,student_id,status,run_json FROM submissions WHERE id=?",
                    (submission_id,),
                ).fetchone()
                review_tables = {
                    row[0]
                    for row in database.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'review_request%'"
                    )
                }
                revision = database.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            self.assertEqual(group, (teacher_id, "Legacy group", "LEGACY"))
            self.assertEqual(member, (group_id, student_id, 3))
            self.assertEqual(assignment, (group_id, teacher_id, "Legacy assignment", "open-2026", "[1]"))
            self.assertEqual(submission, (assignment_id, student_id, "submitted", '{"id":"legacy-run"}'))
            self.assertEqual(
                review_tables,
                {
                    "review_request_assets",
                    "review_request_items",
                    "review_request_recordings",
                    "review_requests",
                },
            )
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
