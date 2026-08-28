from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from trainer.config import PROJECT_ROOT
from trainer.infrastructure.database.migrations import (
    apply_sqlite_baseline,
    head_revision,
    sqlite_url,
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
    "personal_recordings",
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
                personal_recording_columns = {
                    row[1] for row in database.execute("PRAGMA table_info(personal_recordings)")
                }
                review_recording_columns = {
                    row[1] for row in database.execute("PRAGMA table_info(review_request_recordings)")
                }
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
            self.assertEqual(
                personal_recording_columns,
                {
                    "id",
                    "student_id",
                    "run_id",
                    "variant_id",
                    "task_number",
                    "question_number",
                    "label",
                    "storage_key",
                    "mime_type",
                    "size_bytes",
                    "duration_seconds",
                    "created_at",
                    "expires_at",
                },
            )
            self.assertIn("expires_at", review_recording_columns)
            self.assertTrue(
                {"personal_recordings_student_expiry_idx", "review_request_recordings_expiry_idx"}.issubset(
                    sqlite_schema(path)[1]
                )
            )
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

    def test_personal_recording_is_unique_per_student_run_and_position(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                student_id = database.execute(
                    "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                    ("student@example.test", "hash", "Student", "student", 1),
                ).lastrowid
                recording = (
                    student_id,
                    "run-1",
                    "demo-2026",
                    1,
                    1,
                    "Answer",
                    "personal-recordings/1/one.webm",
                    "audio/webm",
                    1,
                    1.0,
                    1,
                    2,
                )
                database.execute(
                    """INSERT INTO personal_recordings(
                           student_id,run_id,variant_id,task_number,question_number,label,storage_key,
                           mime_type,size_bytes,duration_seconds,created_at,expires_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    recording,
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    database.execute(
                        """INSERT INTO personal_recordings(
                               student_id,run_id,variant_id,task_number,question_number,label,storage_key,
                               mime_type,size_bytes,duration_seconds,created_at,expires_at
                           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (*recording[:6], "personal-recordings/1/two.webm", *recording[7:]),
                    )

    def test_upgrade_backfills_review_recording_expiry_from_created_at(self):
        created_at = int(datetime(2026, 8, 31, tzinfo=UTC).timestamp())
        expected_expiry = int(datetime(2027, 2, 28, tzinfo=UTC).timestamp())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                with database:
                    apply_sqlite_baseline(database)
                config = Config(str(PROJECT_ROOT / "alembic.ini"))
                config.set_main_option("sqlalchemy.url", sqlite_url(path))
                command.stamp(config, "20260711_03")
                command.upgrade(config, "20260819_07")
                with database:
                    student_id = database.execute(
                        "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                        ("student@example.test", "hash", "Student", "student", created_at),
                    ).lastrowid
                    request_id = database.execute(
                        "INSERT INTO review_requests(student_id,kind,status,variant_id,run_json) VALUES (?,?,?,?,?)",
                        (student_id, "task", "uploading", "demo-2026", "{}"),
                    ).lastrowid
                    item_id = database.execute(
                        "INSERT INTO review_request_items(request_id,task_number,task_snapshot_json) VALUES (?,?,?)",
                        (request_id, 2, "{}"),
                    ).lastrowid
                    recording_id = database.execute(
                        """INSERT INTO review_request_recordings
                           (item_id,question_number,label,storage_key,mime_type,size_bytes,created_at)
                           VALUES (?,?,?,?,?,?,?)""",
                        (item_id, 1, "Answer", "private/answer.webm", "audio/webm", 1, created_at),
                    ).lastrowid

            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                expires_at = database.execute(
                    "SELECT expires_at FROM review_request_recordings WHERE id=?", (recording_id,)
                ).fetchone()[0]
            self.assertEqual(expires_at, expected_expiry)

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
                    """INSERT INTO review_request_recordings
                       (item_id,question_number,label,storage_key,mime_type,size_bytes,created_at,expires_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (item_id, None, "First", "private/first.webm", "audio/webm", 1, 1, 2),
                )

                with self.assertRaises(sqlite3.IntegrityError):
                    database.execute(
                        """INSERT INTO review_request_recordings
                           (item_id,question_number,label,storage_key,mime_type,size_bytes,created_at,expires_at)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (item_id, None, "Second", "private/second.webm", "audio/webm", 1, 1, 2),
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


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is not configured")
class PostgresMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_url = os.environ["TEST_DATABASE_URL"]
        cls.engine = create_engine(cls.database_url)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as database:
            database.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            database.execute(text("CREATE SCHEMA public"))

    def alembic_config(self) -> Config:
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self.database_url.replace("%", "%%"))
        return config

    def test_head_creates_complete_personal_recording_contract(self):
        command.upgrade(self.alembic_config(), "head")
        with self.engine.connect() as database:
            columns = {
                row[0]
                for row in database.execute(
                    text(
                        """SELECT column_name FROM information_schema.columns
                           WHERE table_schema='public' AND table_name='personal_recordings'"""
                    )
                )
            }
        self.assertEqual(
            columns,
            {
                "id",
                "student_id",
                "run_id",
                "variant_id",
                "task_number",
                "question_number",
                "label",
                "storage_key",
                "mime_type",
                "size_bytes",
                "duration_seconds",
                "created_at",
                "expires_at",
            },
        )

        values = {
            "email": "student@example.test",
            "run_id": "run-1",
            "variant_id": "demo-2026",
            "task_number": 1,
            "question_number": 1,
            "label": "Answer",
            "storage_key": "personal-recordings/1/one.webm",
        }
        with self.engine.begin() as database:
            student_id = database.execute(
                text(
                    """INSERT INTO users(email,password_hash,display_name,role,created_at)
                       VALUES (:email,'hash','Student','student',1) RETURNING id"""
                ),
                values,
            ).scalar_one()
            values["student_id"] = student_id
            database.execute(
                text(
                    """INSERT INTO personal_recordings(
                           student_id,run_id,variant_id,task_number,question_number,label,storage_key,
                           mime_type,size_bytes,duration_seconds,created_at,expires_at
                       ) VALUES (
                           :student_id,:run_id,:variant_id,:task_number,:question_number,:label,:storage_key,
                           'audio/webm',1,1.0,1,2
                       )"""
                ),
                values,
            )
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as database:
                database.execute(
                    text(
                        """INSERT INTO personal_recordings(
                               student_id,run_id,variant_id,task_number,question_number,label,storage_key,
                               mime_type,size_bytes,duration_seconds,created_at,expires_at
                           ) VALUES (
                               :student_id,:run_id,:variant_id,:task_number,:question_number,:label,
                               'personal-recordings/1/two.webm','audio/webm',1,1.0,1,2
                           )"""
                    ),
                    values,
                )

    def test_upgrade_backfills_review_recording_expiry_from_created_at(self):
        created_at = int(datetime(2026, 8, 31, tzinfo=UTC).timestamp())
        expected_expiry = int(datetime(2027, 2, 28, tzinfo=UTC).timestamp())
        config = self.alembic_config()
        command.upgrade(config, "20260819_07")
        with self.engine.begin() as database:
            student_id = database.execute(
                text(
                    """INSERT INTO users(email,password_hash,display_name,role,created_at)
                       VALUES ('student@example.test','hash','Student','student',:created_at) RETURNING id"""
                ),
                {"created_at": created_at},
            ).scalar_one()
            request_id = database.execute(
                text(
                    """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json)
                       VALUES (:student_id,'task','uploading','demo-2026','{}') RETURNING id"""
                ),
                {"student_id": student_id},
            ).scalar_one()
            item_id = database.execute(
                text(
                    """INSERT INTO review_request_items(request_id,task_number,task_snapshot_json)
                       VALUES (:request_id,2,'{}') RETURNING id"""
                ),
                {"request_id": request_id},
            ).scalar_one()
            recording_id = database.execute(
                text(
                    """INSERT INTO review_request_recordings(
                           item_id,question_number,label,storage_key,mime_type,size_bytes,created_at
                       ) VALUES (:item_id,1,'Answer','private/answer.webm','audio/webm',1,:created_at)
                       RETURNING id"""
                ),
                {"item_id": item_id, "created_at": created_at},
            ).scalar_one()
        command.upgrade(config, "head")
        with self.engine.connect() as database:
            expiry = database.execute(
                text("SELECT expires_at FROM review_request_recordings WHERE id=:id"), {"id": recording_id}
            ).scalar_one()
        self.assertEqual(expiry, expected_expiry)


if __name__ == "__main__":
    unittest.main()
