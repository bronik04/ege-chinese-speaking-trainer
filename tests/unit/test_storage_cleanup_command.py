from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import call, patch

from trainer.services.storage_cleanup import CleanupSummary


class StorageCleanupCommandTest(unittest.TestCase):
    @patch("scripts.cleanup_storage.time", side_effect=[100, 4_000])
    @patch("scripts.cleanup_storage.runtime")
    def test_expires_before_processing_and_reports_outcomes(self, runtime, clock):
        service = runtime.storage_cleanup_service.return_value
        service.expire_batch.side_effect = [500, 3]
        service.process_batch.side_effect = [
            CleanupSummary(failed=500, pending=600),
            CleanupSummary(completed=100, failed=1, pending=1),
        ]
        from scripts.cleanup_storage import main

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(), 1)

        runtime.init_database.assert_called_once_with(cleanup=False)
        self.assertEqual(
            service.expire_batch.call_args_list,
            [call(limit=500, now=100), call(limit=500, now=100)],
        )
        self.assertEqual(
            service.process_batch.call_args_list,
            [call(limit=500, now=100), call(limit=500, now=100)],
        )
        clock.assert_called_once_with()
        self.assertEqual(output.getvalue(), "expired=503 completed=100 failed=501 pending=1\n")

    @patch("scripts.cleanup_storage.time", side_effect=[100, 4_000])
    @patch("scripts.cleanup_storage.runtime")
    def test_returns_nonzero_when_cleanup_remains(self, runtime, clock):
        service = runtime.storage_cleanup_service.return_value
        service.expire_batch.return_value = 0
        service.process_batch.return_value = CleanupSummary(completed=0, failed=1, pending=1)
        from scripts.cleanup_storage import main

        self.assertEqual(main(), 1)
        service.process_batch.assert_called_once_with(limit=500, now=100)
        clock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
