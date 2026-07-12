from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trainer.infrastructure.mailer import send_email
from trainer.infrastructure.storage import LocalAudioStorage, storage_from_env


class MailerServiceTest(unittest.TestCase):
    def test_outbox_contains_json_payload_and_is_private(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            self.assertEqual(send_email(root, "user@example.test", "Subject", "Body"), "outbox")
            outbox = root / "outbox.log"
            payload = json.loads(outbox.read_text(encoding="utf-8"))
            self.assertEqual(payload["to"], "user@example.test")
            self.assertEqual(payload["subject"], "Subject")
            self.assertEqual(payload["body"], "Body")
            self.assertEqual(outbox.stat().st_mode & 0o777, 0o600)


class StorageFactoryTest(unittest.TestCase):
    def test_selects_local_backend(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"TRAINER_AUDIO_STORAGE": "local"}, clear=True),
        ):
            self.assertIsInstance(storage_from_env(Path(directory)), LocalAudioStorage)

    def test_rejects_unknown_backend_and_missing_s3_bucket(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"TRAINER_AUDIO_STORAGE": "unknown"}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "must be 'local' or 's3'"):
                    storage_from_env(root)
            with patch.dict(os.environ, {"TRAINER_AUDIO_STORAGE": "s3"}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "TRAINER_S3_BUCKET is required"):
                    storage_from_env(root)


if __name__ == "__main__":
    unittest.main()
