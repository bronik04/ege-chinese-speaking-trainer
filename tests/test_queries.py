import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.database import connect, initialize
from backend.queries import safe_progress
from backend.submissions import create_submission_with_retry


class DatabaseTest(unittest.TestCase):
    def test_initialize_applies_migrations_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "trainer.sqlite3"
            initialize(root, root / "audio", database_path)
            with connect(database_path) as database:
                versions = [
                    row["version"] for row in database.execute("SELECT version FROM schema_migrations ORDER BY version")
                ]
                foreign_keys = database.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(versions, [1, 2, 3, 4, 5, 6, 7])
            self.assertEqual(foreign_keys, 1)

    def test_connection_closes_after_context_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            connection = connect(path)
            with connection as database:
                database.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")


class ProgressParsingTest(unittest.TestCase):
    def test_safe_progress_rejects_invalid_documents(self):
        self.assertEqual(safe_progress(None), {"runs": []})
        self.assertEqual(safe_progress("not json"), {"runs": []})
        self.assertEqual(safe_progress("[]"), {"runs": []})

    def test_safe_progress_preserves_valid_document(self):
        document = safe_progress('{"runs":[{"id":"one"}],"updatedAt":"now"}')
        self.assertEqual(document["runs"][0]["id"], "one")


class ConcurrentSubmissionTest(unittest.TestCase):
    def test_concurrent_attempts_receive_unique_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "trainer.sqlite3"
            initialize(root, root / "audio", path)
            with connect(path) as database:
                teacher = database.execute(
                    "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                    ("t@example.test", "x", "T", "teacher", 1),
                ).lastrowid
                student = database.execute(
                    "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                    ("s@example.test", "x", "S", "student", 1),
                ).lastrowid
                group = database.execute(
                    "INSERT INTO study_groups(teacher_id,name,join_code,created_at) VALUES (?,?,?,?)",
                    (teacher, "G", "ABC123", 1),
                ).lastrowid
                assignment = database.execute(
                    "INSERT INTO assignments(group_id,teacher_id,title,variant_id,tasks_json,created_at) VALUES (?,?,?,?,?,?)",
                    (group, teacher, "A", "demo-2026", "[1]", 1),
                ).lastrowid
            barrier = threading.Barrier(3)

            def submit():
                barrier.wait()
                return create_submission_with_retry(
                    lambda: connect(path), assignment, student, "{}", 2, max_attempts=3
                )[1]

            with ThreadPoolExecutor(max_workers=3) as pool:
                attempts = list(pool.map(lambda _: submit(), range(3)))
            self.assertEqual(sorted(attempts), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
