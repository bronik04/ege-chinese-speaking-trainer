from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, call, patch

from trainer.services.storage_cleanup import CleanupSummary


class StorageCleanupCommandTest(unittest.TestCase):
    @patch("scripts.cleanup_storage.time", side_effect=[100, 4_000])
    @patch("scripts.cleanup_storage.process_cleanup_jobs")
    @patch("scripts.cleanup_storage.expire_recordings", side_effect=[500, 3])
    @patch("scripts.cleanup_storage.runtime")
    def test_expires_before_processing_and_reports_outcomes(self, runtime, expire, process, clock):
        database = Mock()
        runtime.connect.return_value.__enter__.return_value = database
        process.side_effect = [
            CleanupSummary(failed=500, pending=600),
            CleanupSummary(completed=100, failed=1, pending=1),
        ]
        from scripts.cleanup_storage import main

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(), 1)

        runtime.init_database.assert_called_once_with(cleanup=False)
        self.assertEqual(
            expire.call_args_list,
            [call(database, limit=500, now=100), call(database, limit=500, now=100)],
        )
        expected_process = call(
            database,
            audio_root=runtime.AUDIO_DIR,
            material_root=runtime.MATERIAL_ASSET_DIR,
            assignment_root=runtime.ASSIGNMENT_ASSET_DIR,
            limit=500,
            now=100,
        )
        self.assertEqual(process.call_args_list, [expected_process, expected_process])
        clock.assert_called_once_with()
        self.assertIn("expired=503 completed=100 failed=501 pending=1", output.getvalue())

    @patch("scripts.cleanup_storage.time", side_effect=[100, 4_000])
    @patch("scripts.cleanup_storage.process_cleanup_jobs")
    @patch("scripts.cleanup_storage.expire_recordings", return_value=0)
    @patch("scripts.cleanup_storage.runtime")
    def test_returns_nonzero_when_cleanup_remains(self, runtime, _expire, process, clock):
        runtime.connect.return_value.__enter__.return_value = Mock()
        process.return_value = CleanupSummary(completed=0, failed=1, pending=1)
        from scripts.cleanup_storage import main

        self.assertEqual(main(), 1)
        process.assert_called_once_with(
            runtime.connect.return_value.__enter__.return_value,
            audio_root=runtime.AUDIO_DIR,
            material_root=runtime.MATERIAL_ASSET_DIR,
            assignment_root=runtime.ASSIGNMENT_ASSET_DIR,
            limit=500,
            now=100,
        )
        clock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
