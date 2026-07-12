from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from trainer.services.accounts import delete_account_storage
from trainer.services.assignment_assets import copy_assignment_assets_from_env, read_assignment_asset
from trainer.services.recordings import delete_recordings, read_recording, write_recording


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


if __name__ == "__main__":
    unittest.main()
