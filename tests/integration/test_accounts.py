import tempfile
import unittest
from pathlib import Path

from trainer.infrastructure.database.accounts import consume_rate_limit, consume_token, issue_token, record_audit
from trainer.infrastructure.database.core import connect, initialize
from trainer.infrastructure.mailer import send_email


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


if __name__ == "__main__":
    unittest.main()
