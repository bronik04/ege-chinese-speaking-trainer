from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from trainer.api import runtime
from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.services.recordings import delete_recordings, read_recording, write_recording
from trainer.services.storage_cleanup import (
    account_review_storage_keys,
    enqueue_cleanup_job,
    expire_recordings,
    process_cleanup_jobs,
)


class RecordingStorageServiceTest(unittest.TestCase):
    @patch("trainer.services.recordings.storage_from_env", side_effect=RuntimeError("factory failed"))
    def test_cleanup_suppresses_factory_failure(self, _factory):
        delete_recordings(Path("audio"), ["answer.webm"])

    @patch("trainer.services.recordings.storage_from_env")
    def test_read_write_and_delete_delegate_to_selected_storage(self, factory):
        storage = Mock()
        storage.read.return_value = b"audio"
        factory.return_value = storage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.webm"
            source.write_bytes(b"audio")
            write_recording(root, "1/answer.webm", source, "audio/webm")
            self.assertEqual(read_recording(root, "1/answer.webm"), b"audio")
            delete_recordings(root, ["1/answer.webm"])
        storage.put.assert_called_once_with("1/answer.webm", source, "audio/webm")
        storage.delete.assert_called_once_with("1/answer.webm")


class AccountServiceRuntimeTest(unittest.TestCase):
    def test_factory_composes_current_runtime_dependencies_without_cache(self):
        repository = object()
        sender = object()
        service = object()
        with (
            patch.object(runtime, "SQLiteAccountRepository", return_value=repository) as repository_type,
            patch.object(runtime, "MailAccountLinkSender", return_value=sender) as sender_type,
            patch.object(runtime, "AccountService", return_value=service) as service_type,
            patch.object(runtime, "account_public_url", return_value="https://trainer.example"),
            patch.object(runtime, "owner_email", return_value="owner@example.test"),
        ):
            first = runtime.account_service()
            second = runtime.account_service()

        self.assertIs(first, service)
        self.assertIs(second, service)
        self.assertEqual(repository_type.call_count, 2)
        repository_type.assert_called_with(runtime.connect)
        sender_type.assert_called_with(runtime.DATA_DIR, "https://trainer.example")
        service_type.assert_called_with(
            repository,
            sender,
            runtime._process_account_cleanup,
            owner_email="owner@example.test",
            session_days=runtime.SESSION_DAYS,
        )


class StorageCleanupJobServiceTest(unittest.TestCase):
    @patch("trainer.services.storage_cleanup.storage_from_env")
    def test_expiry_removes_metadata_before_failed_physical_delete_and_retries(self, factory):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                student_id = database.execute(
                    "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                    ("student@example.test", "hash", "Student", "student", 1),
                ).lastrowid
                database.execute(
                    """INSERT INTO personal_recordings(student_id,run_id,variant_id,task_number,question_number,
                       label,storage_key,mime_type,size_bytes,duration_seconds,created_at,expires_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (student_id, "run", "demo", 2, 1, "Answer", "expired.webm", "audio/webm", 1, 1.0, 1, 10),
                )
                request_id = database.execute(
                    "INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at) VALUES (?,?,?,?,?,?)",
                    (student_id, "task", "queued", "demo", "{}", 1),
                ).lastrowid
                item_id = database.execute(
                    "INSERT INTO review_request_items(request_id,task_number,task_snapshot_json) VALUES (?,?,?)",
                    (request_id, 2, "{}"),
                ).lastrowid
                database.execute(
                    """INSERT INTO review_request_recordings(
                       item_id,question_number,label,storage_key,mime_type,size_bytes,created_at,expires_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (item_id, 1, "Answer", "expired.webm", "audio/webm", 1, 1, 10),
                )
                database.commit()

                self.assertEqual(expire_recordings(database, now=10, limit=2), 2)
                self.assertEqual(database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0], 0)
                self.assertEqual(database.execute("SELECT COUNT(*) FROM review_request_recordings").fetchone()[0], 0)
                keys = json.loads(database.execute("SELECT audio_keys_json FROM storage_cleanup_jobs").fetchone()[0])
                self.assertEqual(keys, ["expired.webm"])
                factory.return_value.delete.side_effect = OSError("storage unavailable")
                failed = process_cleanup_jobs(
                    database,
                    audio_root=path.parent / "audio",
                    material_root=path.parent / "materials",
                    assignment_root=path.parent / "assignments",
                    now=11,
                )
                self.assertEqual((failed.completed, failed.failed, failed.pending), (0, 1, 1))
                factory.return_value.delete.side_effect = None
                retried = process_cleanup_jobs(
                    database,
                    audio_root=path.parent / "audio",
                    material_root=path.parent / "materials",
                    assignment_root=path.parent / "assignments",
                    now=3611,
                )
                self.assertEqual((retried.completed, retried.failed, retried.pending), (1, 0, 0))

    def test_expiry_respects_shared_limit_and_does_not_enqueue_empty_job(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                student_id = database.execute(
                    "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                    ("student@example.test", "hash", "Student", "student", 1),
                ).lastrowid
                for task_number in (1, 2):
                    database.execute(
                        """INSERT INTO personal_recordings(student_id,run_id,variant_id,task_number,question_number,
                           label,storage_key,mime_type,size_bytes,duration_seconds,created_at,expires_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            student_id,
                            "run",
                            "demo",
                            task_number,
                            1,
                            "Answer",
                            f"{task_number}.webm",
                            "audio/webm",
                            1,
                            1.0,
                            1,
                            10,
                        ),
                    )
                database.commit()
                self.assertEqual(expire_recordings(database, now=9), 0)
                self.assertEqual(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0], 0)
                self.assertEqual(expire_recordings(database, now=10, limit=1), 1)
                self.assertEqual(database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0], 1)

    def test_expiry_selects_oldest_rows_across_personal_and_review_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                student_id = database.execute(
                    "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                    ("oldest@example.test", "hash", "Student", "student", 1),
                ).lastrowid
                database.execute(
                    """INSERT INTO personal_recordings(student_id,run_id,variant_id,task_number,question_number,
                       label,storage_key,mime_type,size_bytes,duration_seconds,created_at,expires_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (student_id, "run", "demo", 2, 1, "Personal", "personal.webm", "audio/webm", 1, 1.0, 1, 20),
                )
                request_id = database.execute(
                    "INSERT INTO review_requests(student_id,kind,status,variant_id,run_json) VALUES (?,?,?,?,?)",
                    (student_id, "task", "queued", "demo", "{}"),
                ).lastrowid
                item_id = database.execute(
                    "INSERT INTO review_request_items(request_id,task_number,task_snapshot_json) VALUES (?,?,?)",
                    (request_id, 2, "{}"),
                ).lastrowid
                database.execute(
                    """INSERT INTO review_request_recordings(
                       item_id,question_number,label,storage_key,mime_type,size_bytes,created_at,expires_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (item_id, None, "Review", "review.webm", "audio/webm", 1, 1, 10),
                )
                database.commit()

                self.assertEqual(expire_recordings(database, now=20, limit=1), 1)
                self.assertEqual(database.execute("SELECT COUNT(*) FROM review_request_recordings").fetchone()[0], 0)
                self.assertEqual(database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0], 1)

    def test_account_audio_keys_include_personal_recordings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                student_id = database.execute(
                    "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                    ("student@example.test", "hash", "Student", "student", 1),
                ).lastrowid
                database.execute(
                    """INSERT INTO personal_recordings(student_id,run_id,variant_id,task_number,question_number,
                       label,storage_key,mime_type,size_bytes,duration_seconds,created_at,expires_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (student_id, "run", "demo", 2, 1, "Answer", "personal.webm", "audio/webm", 1, 1.0, 1, 10),
                )
                audio_keys, _ = account_review_storage_keys(database, student_id)
                self.assertEqual(audio_keys, ["personal.webm"])

    @patch("trainer.api.runtime.process_cleanup_jobs")
    @patch("trainer.api.runtime.expire_recordings", side_effect=OSError("storage unavailable"))
    @patch("trainer.api.runtime.initialize_database")
    @patch.object(runtime.logger, "exception")
    def test_startup_cleanup_failure_is_best_effort(self, log_error, _initialize, _expire, process):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(runtime, "DATA_DIR", root),
                patch.object(runtime, "AUDIO_DIR", root / "audio"),
                patch.object(runtime, "MATERIAL_ASSET_DIR", root / "materials"),
                patch.object(runtime, "REVIEW_ASSET_DIR", root / "assignments"),
            ):
                runtime.init_database()

        process.assert_not_called()
        log_error.assert_called_once_with(
            "Storage cleanup startup attempt failed", extra={"event": "storage_cleanup_startup_failed"}
        )

    @patch("trainer.services.storage_cleanup.storage_from_env")
    def test_failed_job_is_retained_and_successful_retry_removes_it(self, factory):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                job_id = enqueue_cleanup_job(
                    database,
                    audio_keys=["recording.webm"],
                    material_keys=[],
                    assignment_keys=[],
                    now=100,
                )
                factory.return_value.delete.side_effect = OSError("storage unavailable")
                summary = process_cleanup_jobs(
                    database,
                    audio_root=root / "audio",
                    material_root=root / "materials",
                    assignment_root=root / "assignments",
                    now=101,
                )
                self.assertEqual((summary.completed, summary.failed), (0, 1))
                self.assertEqual(
                    database.execute("SELECT attempts FROM storage_cleanup_jobs WHERE id=?", (job_id,)).fetchone()[0], 1
                )
                factory.return_value.delete.side_effect = None
                summary = process_cleanup_jobs(
                    database,
                    audio_root=root / "audio",
                    material_root=root / "materials",
                    assignment_root=root / "assignments",
                    now=102,
                )
                self.assertEqual((summary.completed, summary.failed, summary.pending), (0, 0, 1))
                summary = process_cleanup_jobs(
                    database,
                    audio_root=root / "audio",
                    material_root=root / "materials",
                    assignment_root=root / "assignments",
                    now=3701,
                )
                self.assertEqual((summary.completed, summary.failed), (1, 0))
                self.assertIsNone(
                    database.execute("SELECT id FROM storage_cleanup_jobs WHERE id=?", (job_id,)).fetchone()
                )

    @patch("trainer.services.storage_cleanup.storage_from_env")
    def test_cleanup_job_is_invisible_until_its_available_time(self, factory):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                enqueue_cleanup_job(
                    database,
                    audio_keys=["uploading.webm"],
                    material_keys=[],
                    assignment_keys=[],
                    now=100,
                    available_at=200,
                )
                deferred = process_cleanup_jobs(
                    database,
                    audio_root=root / "audio",
                    material_root=root / "materials",
                    assignment_root=root / "assignments",
                    now=199,
                )
                self.assertEqual((deferred.completed, deferred.failed, deferred.pending), (0, 0, 1))
                factory.return_value.delete.assert_not_called()

                available = process_cleanup_jobs(
                    database,
                    audio_root=root / "audio",
                    material_root=root / "materials",
                    assignment_root=root / "assignments",
                    now=200,
                )
                self.assertEqual((available.completed, available.failed, available.pending), (1, 0, 0))
                factory.return_value.delete.assert_called_once_with("uploading.webm")


if __name__ == "__main__":
    unittest.main()
