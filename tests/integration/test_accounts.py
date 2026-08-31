import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trainer.api import runtime
from trainer.api.controllers import auth
from trainer.api.results import RequestContext
from trainer.api.schemas import DeleteAccountRequest
from trainer.domain.accounts import password_hash
from trainer.domain.recording_retention import expires_at
from trainer.infrastructure.database.accounts import consume_rate_limit, consume_token, issue_token, record_audit
from trainer.infrastructure.database.core import connect, initialize
from trainer.infrastructure.mailer import send_email
from trainer.services.storage_cleanup import CleanupSummary, process_cleanup_jobs


class AccountSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database_path = self.root / "trainer.sqlite3"
        initialize(self.root, self.root / "audio", self.database_path)
        with connect(self.database_path) as database:
            cursor = database.execute(
                "INSERT INTO users(email, password_hash, display_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
                ("user@example.test", "hash", "User", "student", 1000),
            )
            self.user_id = cursor.lastrowid

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_rate_limit_survives_new_connection(self):
        for offset in range(8):
            with connect(self.database_path) as database:
                self.assertEqual(
                    consume_rate_limit(database, "login", "127.0.0.1", "user@example.test", 1000 + offset), 0
                )
        with connect(self.database_path) as database:
            retry_after = consume_rate_limit(database, "login", "127.0.0.1", "user@example.test", 1008)
        self.assertGreater(retry_after, 0)
        with connect(self.database_path) as database:
            self.assertGreater(consume_rate_limit(database, "login", "127.0.0.1", "user@example.test", 1009), 0)

    def test_tokens_are_single_use_and_expire(self):
        with connect(self.database_path) as database:
            token = issue_token(database, "password_reset", self.user_id, 1000)
        with connect(self.database_path) as database:
            self.assertEqual(consume_token(database, "password_reset", token, 1001)["id"], self.user_id)
            self.assertIsNone(consume_token(database, "password_reset", token, 1002))
            expired = issue_token(database, "email_verification", self.user_id, 1000)
        with connect(self.database_path) as database:
            self.assertIsNone(consume_token(database, "email_verification", expired, 1000 + 86401))

    def test_audit_survives_account_deletion(self):
        with connect(self.database_path) as database:
            record_audit(database, "account_deleted", user_id=self.user_id, email="user@example.test", now=1000)
            database.execute("DELETE FROM users WHERE id = ?", (self.user_id,))
        with connect(self.database_path) as database:
            row = database.execute("SELECT user_id, email FROM audit_log").fetchone()
        self.assertIsNone(row["user_id"])
        self.assertEqual(row["email"], "user@example.test")

    def test_local_email_delivery_uses_private_outbox(self):
        delivery = send_email(self.root, "user@example.test", "Subject", "Body")
        self.assertEqual(delivery, "outbox")
        outbox = self.root / "outbox.log"
        self.assertTrue(outbox.is_file())
        self.assertEqual(outbox.stat().st_mode & 0o777, 0o600)

    def test_account_deletion_job_removes_review_audio_and_copied_assets(self):
        audio_root = self.root / "audio"
        material_root = self.root / "material-assets"
        copied_asset_root = self.root / "assignment-assets"
        audio_key = "review-requests/1/answer.webm"
        copied_asset_key = "review-requests/1/image.webp"
        with connect(self.database_path) as database:
            database.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (password_hash("password123"), self.user_id),
            )
            request_id = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at)
                   VALUES (?,?,?,?,?,?)""",
                (self.user_id, "task", "queued", "open-2026", '{"id":"review-run"}', 1001),
            ).lastrowid
            item_id = database.execute(
                """INSERT INTO review_request_items(request_id,task_number,task_snapshot_json)
                   VALUES (?,?,?)""",
                (request_id, 2, "{}"),
            ).lastrowid
            database.execute(
                """INSERT INTO review_request_recordings(
                       item_id,question_number,label,storage_key,mime_type,size_bytes,created_at,expires_at
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (item_id, None, "Answer", audio_key, "audio/webm", 5, 1001, expires_at(1001)),
            )
            database.execute(
                """INSERT INTO review_request_assets(request_id,storage_key,mime_type,size_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (request_id, copied_asset_key, "image/webp", 5, 1001),
            )
        audio_path = audio_root / audio_key
        copied_asset_path = copied_asset_root / copied_asset_key
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        copied_asset_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"audio")
        copied_asset_path.write_bytes(b"image")

        user = {
            "id": self.user_id,
            "email": "user@example.test",
            "displayName": "User",
            "role": "student",
            "emailVerified": False,
        }
        with (
            patch.object(runtime, "DB_PATH", self.database_path),
            patch.object(runtime, "AUDIO_DIR", audio_root),
            patch.object(runtime, "MATERIAL_ASSET_DIR", material_root),
            patch.object(runtime, "REVIEW_ASSET_DIR", copied_asset_root),
            patch.object(runtime, "process_cleanup_jobs", return_value=CleanupSummary(pending=1)),
        ):
            result = auth.account_delete(
                DeleteAccountRequest(password="password123"),
                user,
                RequestContext(client_ip="127.0.0.1", user_agent="account-test"),
            )

        self.assertEqual(result.payload, {"ok": True})
        with connect(self.database_path) as database:
            self.assertIsNone(database.execute("SELECT id FROM users WHERE id=?", (self.user_id,)).fetchone())
            self.assertEqual(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0], 1)
        self.assertTrue(audio_path.is_file())
        self.assertTrue(copied_asset_path.is_file())

        with patch.dict(os.environ, {"TRAINER_AUDIO_STORAGE": "local"}):
            with connect(self.database_path) as database:
                available_at = database.execute(
                    "SELECT available_at FROM storage_cleanup_jobs ORDER BY id DESC LIMIT 1"
                ).fetchone()[0]
                summary = process_cleanup_jobs(
                    database,
                    audio_root=audio_root,
                    material_root=material_root,
                    assignment_root=copied_asset_root,
                    now=available_at,
                )

        self.assertEqual((summary.completed, summary.failed, summary.pending), (1, 0, 0))
        self.assertFalse(audio_path.exists())
        self.assertFalse(copied_asset_path.exists())


if __name__ == "__main__":
    unittest.main()
