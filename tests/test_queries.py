import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.database import connect, initialize
from backend.queries import safe_progress


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
            self.assertEqual(versions, [1, 2, 3, 4, 5, 6])
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


if __name__ == "__main__":
    unittest.main()
