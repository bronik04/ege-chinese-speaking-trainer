from __future__ import annotations

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
from trainer.services.storage_cleanup import enqueue_cleanup_job, process_cleanup_jobs


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
