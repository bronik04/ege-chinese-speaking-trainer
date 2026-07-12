import os
import unittest
from unittest.mock import patch

from trainer.api.dependencies import account_public_url


class AccountPublicUrlTest(unittest.TestCase):
    def test_uses_configured_public_url_without_trailing_slash(self):
        with patch.dict(os.environ, {"TRAINER_PUBLIC_URL": "https://trainer.example/"}):
            self.assertEqual(account_public_url(), "https://trainer.example")

    def test_uses_fixed_local_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(account_public_url(), "http://127.0.0.1:8080")


if __name__ == "__main__":
    unittest.main()
