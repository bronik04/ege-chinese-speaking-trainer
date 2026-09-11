import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.infrastructure.database.progress_repository import SQLiteProgressRepository
from trainer.services.progress_repository import ProgressDataError, ProgressRecord


class SQLiteProgressRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "trainer.sqlite3"
        upgrade_sqlite_database(self.path)
        self.repository = SQLiteProgressRepository(self.connect)
        with closing(self.connect()) as database, database:
            for user_id in (1, 2):
                database.execute(
                    "INSERT INTO users(id,email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?,?)",
                    (user_id, f"student{user_id}@example.test", "hash", "Student", "student", 1),
                )

    def connect(self, factory=sqlite3.Connection):
        database = sqlite3.connect(self.path, factory=factory)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def test_committed_round_trip_update_and_user_isolation(self):
        self.assertIsNone(self.repository.get(1))
        first = {"version": 2, "runs": [], "extra": "中文", "updatedAt": "client"}
        self.repository.save(1, first, 1000)
        self.assertEqual(self.repository.get(1), ProgressRecord(first, 1000))
        self.assertIsNone(self.repository.get(2))
        self.repository.save(2, {"version": 2, "extra": "other"}, 1001)
        self.repository.save(1, {"version": 2}, 1002)
        self.assertEqual(self.repository.get(1), ProgressRecord({"version": 2}, 1002))
        self.assertEqual(self.repository.get(2).document["extra"], "other")
        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM user_progress").fetchone()[0], 2)

    def test_json_encoding_is_compact_and_unicode_preserving(self):
        document = {"version": 2, "extra": "中文"}
        self.repository.save(1, document, 1000)
        with closing(self.connect()) as database:
            value = database.execute("SELECT progress_json FROM user_progress WHERE user_id=1").fetchone()[0]
        self.assertEqual(value, '{"version":2,"extra":"中文"}')

    def test_commit_failure_rolls_back_update(self):
        class FailingCommit(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError("commit failed")

        self.repository.save(1, {"version": 2, "extra": "old"}, 1000)
        failing = SQLiteProgressRepository(lambda: self.connect(FailingCommit))
        with self.assertRaisesRegex(sqlite3.OperationalError, "commit failed"):
            failing.save(1, {"version": 2, "extra": "new"}, 1001)
        self.assertEqual(self.repository.get(1), ProgressRecord({"version": 2, "extra": "old"}, 1000))

    def test_bad_json_and_non_object_roots_raise_progress_data_error(self):
        for encoded in ("not-json", "[]", "null"):
            with self.subTest(encoded=encoded), closing(self.connect()) as database, database:
                database.execute(
                    """INSERT INTO user_progress(user_id,progress_json,updated_at) VALUES (1,?,1000)
                       ON CONFLICT(user_id) DO UPDATE SET progress_json=excluded.progress_json""",
                    (encoded,),
                )
            with self.assertRaises(ProgressDataError):
                self.repository.get(1)

    def test_serialization_failure_preserves_existing_document(self):
        self.repository.save(1, {"version": 2}, 1000)
        with self.assertRaises(TypeError):
            self.repository.save(1, {"version": 2, "extra": object()}, 1001)
        self.assertEqual(self.repository.get(1), ProgressRecord({"version": 2}, 1000))
