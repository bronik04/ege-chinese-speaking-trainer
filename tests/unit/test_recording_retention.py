from __future__ import annotations

import unittest
from datetime import UTC, datetime

from trainer.domain.recording_retention import expires_at, is_expired


class RecordingRetentionTest(unittest.TestCase):
    def test_expiry_uses_calendar_months_and_clamps_month_end(self):
        created = int(datetime(2026, 8, 31, tzinfo=UTC).timestamp())
        expiry = expires_at(created)

        self.assertEqual(datetime.fromtimestamp(expiry, UTC), datetime(2027, 2, 28, tzinfo=UTC))
        self.assertTrue(is_expired(expiry, expiry))


if __name__ == "__main__":
    unittest.main()
