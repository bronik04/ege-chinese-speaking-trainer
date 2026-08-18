from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from trainer.services.storage_cleanup import CleanupSummary


class StorageCleanupCommandTest(unittest.TestCase):
    @patch("scripts.cleanup_storage.process_cleanup_jobs")
    @patch("scripts.cleanup_storage.runtime")
    def test_returns_nonzero_when_cleanup_remains(self, runtime, process):
        runtime.connect.return_value.__enter__.return_value = Mock()
        process.return_value = CleanupSummary(completed=0, failed=1, pending=1)
        from scripts.cleanup_storage import main

        self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
