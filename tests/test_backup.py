import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.backup import create_backup


class BackupTest(unittest.TestCase):
    def test_backup_copies_database_and_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            output = root / "backups"
            (data / "audio/1").mkdir(parents=True)
            (data / "audio/1/sample.webm").write_bytes(b"audio")
            with closing(sqlite3.connect(data / "trainer.sqlite3")) as database:
                with database:
                    database.execute("CREATE TABLE sample(value TEXT)")
                    database.execute("INSERT INTO sample VALUES ('ok')")
            output.mkdir()
            backup = create_backup(data, output, 2)
            with closing(sqlite3.connect(backup / "trainer.sqlite3")) as database:
                self.assertEqual(database.execute("SELECT value FROM sample").fetchone()[0], "ok")
            self.assertTrue((backup / "audio.tar.gz").is_file())


if __name__ == "__main__":
    unittest.main()
