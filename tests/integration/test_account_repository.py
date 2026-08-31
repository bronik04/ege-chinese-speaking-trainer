from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from trainer.domain.accounts import password_hash, token_digest
from trainer.infrastructure.database.account_repository import SQLiteAccountRepository
from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.services.account_repository import (
    AccountAuditEvent,
    AccountConflictError,
    AccountRequestMetadata,
)
from trainer.services.accounts import AccountError, AccountService


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

    def seed_account_storage_graph(self):
        user_id = self.create_user(role="teacher")
        legacy_audio = "legacy/submission-answer.webm"
        review_audio = "review-requests/1/review-answer.webm"
        personal_audio = "personal-recordings/1/personal-answer.webm"
        material_key = "materials/1/source.webp"
        assignment_key = "assignments/1/copied.webp"
        review_asset_key = "review-requests/1/copied.webp"
        with closing(self.connect()) as database, database:
            group_id = database.execute(
                "INSERT INTO study_groups(teacher_id,name,join_code,created_at) VALUES (?,?,?,?)",
                (user_id, "Group", "ACCOUNT1", 1),
            ).lastrowid
            assignment_id = database.execute(
                """INSERT INTO assignments(
                       group_id,teacher_id,title,variant_id,tasks_json,due_at,created_at
                   ) VALUES (?,?,?,?,?,?,?)""",
                (group_id, user_id, "Assignment", "open-2026", "[2]", None, 1),
            ).lastrowid
            submission_id = database.execute(
                """INSERT INTO submissions(
                       assignment_id,student_id,attempt_number,status,run_json,submitted_at
                   ) VALUES (?,?,?,?,?,?)""",
                (assignment_id, user_id, 1, "submitted", "{}", 2),
            ).lastrowid
            database.execute(
                """INSERT INTO recordings(
                       submission_id,task_number,question_number,label,file_name,mime_type,size_bytes,created_at
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (submission_id, 2, None, "Legacy", legacy_audio, "audio/webm", 1, 2),
            )
            material_id = database.execute(
                """INSERT INTO materials(
                       slug,owner_id,kind,task_number,title,year,source,status,content_json,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ("account-material", user_id, "task", 2, "Material", 2026, "Test", "draft", "{}", 1, 1),
            ).lastrowid
            database.execute(
                """INSERT INTO material_assets(material_id,storage_key,mime_type,size_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (material_id, material_key, "image/webp", 1, 1),
            )
            database.execute(
                """INSERT INTO assignment_material_assets(
                       assignment_id,storage_key,mime_type,size_bytes,created_at
                   ) VALUES (?,?,?,?,?)""",
                (assignment_id, assignment_key, "image/webp", 1, 1),
            )
            request_id = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, "task", "uploading", "open-2026", "{}", None),
            ).lastrowid
            item_id = database.execute(
                """INSERT INTO review_request_items(request_id,task_number,task_snapshot_json)
                   VALUES (?,?,?)""",
                (request_id, 2, "{}"),
            ).lastrowid
            database.execute(
                """INSERT INTO review_request_recordings(
                       item_id,question_number,label,storage_key,mime_type,size_bytes,duration_seconds,
                       created_at,expires_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (item_id, None, "Review", review_audio, "audio/webm", 1, 1.0, 2, 9999999999),
            )
            database.execute(
                """INSERT INTO review_request_assets(request_id,storage_key,mime_type,size_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (request_id, review_asset_key, "image/webp", 1, 1),
            )
            database.execute(
                """INSERT INTO personal_recordings(
                       student_id,run_id,variant_id,task_number,question_number,label,storage_key,mime_type,
                       size_bytes,duration_seconds,created_at,expires_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id,
                    "run-1",
                    "open-2026",
                    2,
                    1,
                    "Personal",
                    personal_audio,
                    "audio/webm",
                    1,
                    1.0,
                    2,
                    9999999999,
                ),
            )
        return (
            user_id,
            {legacy_audio, review_audio, personal_audio},
            {material_key},
            {assignment_key, review_asset_key},
        )

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

    def test_account_cleanup_collects_every_key_before_user_cascade(self):
        user_id, expected_audio, expected_material, expected_assignment = self.seed_account_storage_graph()

        with self.repository.transaction() as transaction:
            transaction.enqueue_account_cleanup(user_id, 2000)
            transaction.audit(
                AccountAuditEvent(
                    "account_deleted",
                    self.metadata,
                    2000,
                    user_id=user_id,
                    email="user@example.test",
                )
            )
            transaction.delete_user(user_id)

        with closing(self.connect()) as database:
            self.assertIsNone(database.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone())
            job = database.execute(
                """SELECT audio_keys_json,material_keys_json,assignment_keys_json
                   FROM storage_cleanup_jobs"""
            ).fetchone()
            audit = database.execute("SELECT user_id,email,action FROM audit_log").fetchone()

        self.assertEqual(set(json.loads(job["audio_keys_json"])), expected_audio)
        self.assertEqual(set(json.loads(job["material_keys_json"])), expected_material)
        self.assertEqual(set(json.loads(job["assignment_keys_json"])), expected_assignment)
        self.assertEqual(
            (audit["user_id"], audit["email"], audit["action"]),
            (None, "user@example.test", "account_deleted"),
        )

    def test_cleanup_job_and_user_delete_roll_back_together(self):
        user_id = self.create_user()

        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.repository.transaction() as transaction:
                transaction.enqueue_account_cleanup(user_id, 2000)
                transaction.delete_user(user_id)
                raise RuntimeError("rollback")

        with closing(self.connect()) as database:
            self.assertIsNotNone(database.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone())
            self.assertEqual(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0], 0)

    def test_missing_account_deletion_keeps_semantic_error_and_durable_audit(self):
        user_id = self.create_user(encoded_password=password_hash("password123"))
        with self.repository.transaction() as transaction:
            transaction.delete_user(user_id)
        service = AccountService(
            self.repository,
            object(),
            lambda: None,
            owner_email="",
            clock=lambda: 2000,
        )

        with self.assertRaises(AccountError) as raised:
            service.delete_account(
                user_id,
                "user@example.test",
                "password123",
                self.metadata,
            )

        self.assertEqual(raised.exception.reason, "invalid_password")
        with closing(self.connect()) as database:
            audit = database.execute(
                "SELECT user_id,email,action FROM audit_log WHERE action='account_deletion_failed'"
            ).fetchone()
        self.assertEqual(
            (audit["user_id"], audit["email"], audit["action"]),
            (None, "user@example.test", "account_deletion_failed"),
        )


if __name__ == "__main__":
    unittest.main()
