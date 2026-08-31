from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from trainer.domain.accounts import token_digest
from trainer.infrastructure.database.account_repository import SQLiteAccountRepository
from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.services.account_repository import (
    AccountAuditEvent,
    AccountConflictError,
    AccountRequestMetadata,
)


class SQLiteAccountRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "trainer.sqlite3"
        upgrade_sqlite_database(self.database_path)
        self.repository = SQLiteAccountRepository(self.connect)
        self.metadata = AccountRequestMetadata("127.0.0.1", "repository-test")

    def tearDown(self):
        self.directory.cleanup()

    def connect(self):
        database = sqlite3.connect(self.database_path)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def create_user(
        self,
        email: str = "user@example.test",
        *,
        encoded_password: str = "encoded-password",
        role: str = "student",
        created_at: int = 1000,
    ) -> int:
        with self.repository.transaction() as transaction:
            return transaction.create_user(email, encoded_password, "User", role, created_at)

    def test_transaction_commits_and_rolls_back_user_and_audit_together(self):
        with self.repository.transaction() as transaction:
            user_id = transaction.create_user(
                "user@example.test",
                "hash",
                "User",
                "student",
                1000,
            )
            transaction.audit(
                AccountAuditEvent(
                    "account_registered",
                    self.metadata,
                    1000,
                    user_id=user_id,
                    email="user@example.test",
                )
            )

        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
            self.assertEqual(
                database.execute("SELECT action FROM audit_log").fetchone()[0],
                "account_registered",
            )

        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.repository.transaction() as transaction:
                transaction.create_user(
                    "rolled-back@example.test",
                    "hash",
                    "User",
                    "student",
                    1001,
                )
                raise RuntimeError("rollback")

        with closing(self.connect()) as database:
            self.assertIsNone(
                database.execute(
                    "SELECT id FROM users WHERE email=?",
                    ("rolled-back@example.test",),
                ).fetchone()
            )

    def test_duplicate_email_is_adapter_neutral(self):
        self.create_user("same@example.test")

        with self.assertRaises(AccountConflictError):
            with self.repository.transaction() as transaction:
                transaction.create_user(
                    "same@example.test",
                    "hash",
                    "User",
                    "student",
                    1001,
                )

    def test_user_reads_and_mutations_map_complete_records(self):
        user_id = self.create_user(encoded_password="old-hash")

        with self.repository.transaction() as transaction:
            by_email = transaction.user_by_email("user@example.test")
            by_id = transaction.user_by_id(user_id)
            transaction.verify_email(user_id, 1200)
            transaction.replace_password(user_id, "new-hash")
        with self.repository.transaction() as transaction:
            updated = transaction.user_by_id(user_id)

        self.assertEqual(
            (
                by_email.id,
                by_email.email,
                by_email.display_name,
                by_email.role,
                by_email.email_verified_at,
                by_email.password_hash,
            ),
            (user_id, "user@example.test", "User", "student", None, "old-hash"),
        )
        self.assertEqual(by_id, by_email)
        self.assertEqual((updated.email_verified_at, updated.password_hash), (1200, "new-hash"))
        with self.repository.transaction() as transaction:
            self.assertIsNone(transaction.user_by_email("missing@example.test"))
            self.assertIsNone(transaction.user_by_id(404))

    def test_session_stores_digest_and_current_user_honors_expiry(self):
        user_id = self.create_user()
        with self.repository.transaction() as transaction:
            token = transaction.create_session(user_id, 2000, 1000)

        with closing(self.connect()) as database:
            stored = database.execute("SELECT token_hash FROM sessions").fetchone()[0]
        self.assertEqual(stored, token_digest(token))
        self.assertNotEqual(stored, token)
        self.assertEqual(self.repository.current_user(token, 1999).id, user_id)
        self.assertIsNone(self.repository.current_user(token, 2000))

        with self.repository.transaction() as transaction:
            self.assertEqual(transaction.session_identity(token).email, "user@example.test")
            transaction.delete_session(token)
        with self.repository.transaction() as transaction:
            self.assertIsNone(transaction.session_identity(token))

    def test_delete_user_sessions_only_revokes_the_selected_account(self):
        first_id = self.create_user("first@example.test")
        second_id = self.create_user("second@example.test")
        with self.repository.transaction() as transaction:
            first_token = transaction.create_session(first_id, 2000, 1000)
            second_token = transaction.create_session(second_id, 2000, 1000)
            transaction.delete_user_sessions(first_id)

        self.assertIsNone(self.repository.current_user(first_token, 1001))
        self.assertEqual(self.repository.current_user(second_token, 1001).id, second_id)

    def test_rate_limit_persists_across_transactions_and_clear_removes_it(self):
        for offset in range(8):
            with self.repository.transaction() as transaction:
                self.assertEqual(
                    transaction.consume_rate_limit(
                        "login",
                        "127.0.0.1",
                        "user@example.test",
                        1000 + offset,
                    ),
                    0,
                )
        with self.repository.transaction() as transaction:
            self.assertGreater(
                transaction.consume_rate_limit(
                    "login",
                    "127.0.0.1",
                    "user@example.test",
                    1008,
                ),
                0,
            )
            transaction.clear_rate_limit("login", "127.0.0.1", "user@example.test")
        with self.repository.transaction() as transaction:
            self.assertEqual(
                transaction.consume_rate_limit(
                    "login",
                    "127.0.0.1",
                    "user@example.test",
                    1009,
                ),
                0,
            )

    def test_tokens_are_single_use_replace_previous_and_expire(self):
        user_id = self.create_user()
        with self.repository.transaction() as transaction:
            first = transaction.issue_token("password_reset", user_id, 1000)
            second = transaction.issue_token("password_reset", user_id, 1001)
        with self.repository.transaction() as transaction:
            self.assertIsNone(transaction.consume_token("password_reset", first, 1002))
            self.assertEqual(
                transaction.consume_token("password_reset", second, 1002).id,
                user_id,
            )
            self.assertIsNone(transaction.consume_token("password_reset", second, 1003))
            expired = transaction.issue_token("email_verification", user_id, 1000)
        with self.repository.transaction() as transaction:
            self.assertIsNone(
                transaction.consume_token(
                    "email_verification",
                    expired,
                    1000 + 86401,
                )
            )

    def test_audit_events_preserve_order_limit_normalization_and_details(self):
        user_id = self.create_user("USER@example.test")
        with self.repository.transaction() as transaction:
            transaction.audit(
                AccountAuditEvent(
                    "older",
                    AccountRequestMetadata("x" * 80, "a" * 350),
                    1000,
                    user_id=user_id,
                    email=" USER@example.test ",
                    details={"sequence": 1},
                )
            )
            transaction.audit(
                AccountAuditEvent(
                    "newer",
                    self.metadata,
                    1001,
                    user_id=user_id,
                    email="user@example.test",
                    details={"sequence": 2},
                )
            )

        events = self.repository.audit_events(user_id, 1)

        self.assertEqual(len(events), 1)
        self.assertEqual(
            (
                events[0].action,
                events[0].ip_address,
                events[0].user_agent,
                events[0].details,
                events[0].created_at,
            ),
            ("newer", "127.0.0.1", "repository-test", {"sequence": 2}, 1001),
        )
        with closing(self.connect()) as database:
            older = database.execute(
                "SELECT email,ip_address,user_agent FROM audit_log WHERE action='older'"
            ).fetchone()
        self.assertEqual(older["email"], "user@example.test")
        self.assertEqual(len(older["ip_address"]), 64)
        self.assertEqual(len(older["user_agent"]), 300)


if __name__ == "__main__":
    unittest.main()
