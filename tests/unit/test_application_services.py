from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.services.accounts import delete_account_storage
from trainer.services.assignment_assets import copy_assignment_assets_from_env, read_assignment_asset
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


class AssignmentStorageServiceTest(unittest.TestCase):
    @patch("trainer.services.assignment_assets.storage_from_env")
    @patch("trainer.services.assignment_assets.copy_assignment_assets")
    def test_factory_wrapper_supplies_source_and_target_storage(self, copy_assets, factory):
        source_storage = Mock()
        target_storage = Mock()
        factory.side_effect = [source_storage, target_storage]
        copy_assets.return_value = {"tasks": {}}
        database = Mock()
        result = copy_assignment_assets_from_env(database, 12, {"tasks": {}}, Path("materials"), Path("assignments"))
        self.assertEqual(result, {"tasks": {}})
        copy_assets.assert_called_once_with(database, 12, {"tasks": {}}, source_storage, target_storage)

    @patch("trainer.services.assignment_assets.storage_from_env")
    def test_reads_assignment_asset_through_factory(self, factory):
        factory.return_value.read.return_value = b"image"
        self.assertEqual(read_assignment_asset(Path("assignments"), "asset.webp"), b"image")


class AccountStorageServiceTest(unittest.TestCase):
    @patch("trainer.services.accounts.storage_from_env")
    def test_account_cleanup_uses_each_private_storage_root(self, factory):
        audio = Mock()
        materials = Mock()
        assignments = Mock()
        factory.side_effect = [audio, materials, assignments]
        delete_account_storage(
            Path("audio"),
            ["recording.webm"],
            Path("materials"),
            ["material.webp"],
            Path("assignments"),
            ["assignment.webp"],
        )
        audio.delete.assert_called_once_with("recording.webm")
        materials.delete.assert_called_once_with("material.webp")
        assignments.delete.assert_called_once_with("assignment.webp")


class StorageCleanupJobServiceTest(unittest.TestCase):
    def test_expiry_removes_archive_and_review_metadata_and_queues_unique_audio_keys(self):
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
                self.assertEqual((summary.completed, summary.failed), (1, 0))
                self.assertIsNone(
                    database.execute("SELECT id FROM storage_cleanup_jobs WHERE id=?", (job_id,)).fetchone()
                )

    @patch("trainer.services.accounts.storage_from_env")
    def test_account_cleanup_propagates_storage_failure(self, factory):
        factory.return_value.delete.side_effect = OSError("storage unavailable")
        with self.assertRaisesRegex(OSError, "storage unavailable"):
            delete_account_storage(Path("audio"), ["recording.webm"], Path("materials"), [], Path("assignments"), [])

    @patch("trainer.services.accounts.storage_from_env")
    def test_account_cleanup_removes_every_key_despite_one_failure(self, factory):
        audio = Mock()
        audio.delete.side_effect = [OSError("first key is unreachable"), None]
        assignments = Mock()
        factory.side_effect = [audio, Mock(), assignments]

        with self.assertRaisesRegex(OSError, "first key is unreachable"):
            delete_account_storage(
                Path("audio"),
                ["broken.webm", "second.webm"],
                Path("materials"),
                [],
                Path("assignments"),
                ["assignment.webp"],
            )

        # Один сбойный ключ не должен оставлять остальные приватные файлы на диске.
        self.assertEqual([call.args[0] for call in audio.delete.call_args_list], ["broken.webm", "second.webm"])
        assignments.delete.assert_called_once_with("assignment.webp")


if __name__ == "__main__":
    unittest.main()
