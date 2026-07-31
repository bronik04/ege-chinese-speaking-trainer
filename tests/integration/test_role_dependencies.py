from __future__ import annotations

import unittest

from trainer.api.dependencies import require_teacher
from trainer.api.errors import ApiError


class FakeRequest:
    def __init__(self, cookie: str = ""):
        self.headers = {"Cookie": cookie, "User-Agent": "test"}
        self.client = type("Client", (), {"host": "127.0.0.1"})()


class RoleDependencyTest(unittest.TestCase):
    def test_missing_session_raises_authentication_required(self):
        with self.assertRaises(ApiError) as raised:
            require_teacher(FakeRequest())

        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.code, "authentication_required")


if __name__ == "__main__":
    unittest.main()
