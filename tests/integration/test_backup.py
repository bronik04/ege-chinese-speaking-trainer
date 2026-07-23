import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.backup import create_backup
from scripts.sqlite_restore_smoke import restore_sqlite_backup


class BackupTest(unittest.TestCase):
    def test_backup_copies_database_and_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            output = root / "backups"
            (data / "audio/1").mkdir(parents=True)
            (data / "audio/1/sample.webm").write_bytes(b"audio")
            (data / "material-assets/materials/1").mkdir(parents=True)
            (data / "material-assets/materials/1/photo.webp").write_bytes(b"photo")
            (data / "assignment-assets/assignments/1").mkdir(parents=True)
            (data / "assignment-assets/assignments/1/photo.webp").write_bytes(b"snapshot")
            with closing(sqlite3.connect(data / "trainer.sqlite3")) as database:
                with database:
                    database.execute("CREATE TABLE sample(value TEXT)")
                    database.execute("INSERT INTO sample VALUES ('ok')")
            output.mkdir()
            backup = create_backup(data, output, 2)
            with closing(sqlite3.connect(backup / "trainer.sqlite3")) as database:
                self.assertEqual(database.execute("SELECT value FROM sample").fetchone()[0], "ok")
            self.assertTrue((backup / "audio.tar.gz").is_file())
            self.assertTrue((backup / "material-assets.tar.gz").is_file())
            self.assertTrue((backup / "assignment-assets.tar.gz").is_file())

    def test_restore_accepts_backup_without_assignment_assets(self):
        # Копии, снятые до появления каталога assignment-assets, обязаны
        # восстанавливаться: иначе первый же деплой обнуляет всю retention-историю.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            output = root / "backups"
            restored = root / "restored"
            (data / "audio/1").mkdir(parents=True)
            (data / "audio/1/sample.webm").write_bytes(b"audio")
            (data / "material-assets/materials/1").mkdir(parents=True)
            (data / "material-assets/materials/1/photo.webp").write_bytes(b"photo")
            with closing(sqlite3.connect(data / "trainer.sqlite3")) as database:
                with database:
                    database.execute("CREATE TABLE sample(value TEXT)")
                    database.execute("INSERT INTO sample VALUES ('legacy')")
            output.mkdir()
            backup = create_backup(data, output, 1)
            (backup / "assignment-assets.tar.gz").unlink()

            restore_sqlite_backup(backup, restored)

            with closing(sqlite3.connect(restored / "trainer.sqlite3")) as database:
                self.assertEqual(database.execute("SELECT value FROM sample").fetchone()[0], "legacy")
            self.assertEqual((restored / "audio/1/sample.webm").read_bytes(), b"audio")

    def test_restore_requires_the_database_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty_backup = root / "backup"
            empty_backup.mkdir()
            with self.assertRaisesRegex(RuntimeError, "trainer.sqlite3"):
                restore_sqlite_backup(empty_backup, root / "restored")

    def test_restore_recovers_database_audio_and_material_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            output = root / "backups"
            restored = root / "restored"
            (data / "audio/1").mkdir(parents=True)
            (data / "audio/1/sample.webm").write_bytes(b"audio")
            (data / "material-assets/materials/1").mkdir(parents=True)
            (data / "material-assets/materials/1/photo.webp").write_bytes(b"photo")
            (data / "assignment-assets/assignments/1").mkdir(parents=True)
            (data / "assignment-assets/assignments/1/photo.webp").write_bytes(b"snapshot")
            with closing(sqlite3.connect(data / "trainer.sqlite3")) as database:
                with database:
                    database.execute("CREATE TABLE sample(value TEXT)")
                    database.execute("INSERT INTO sample VALUES ('restored')")
            output.mkdir()

            backup = create_backup(data, output, 1)
            restore_sqlite_backup(backup, restored)

            with closing(sqlite3.connect(restored / "trainer.sqlite3")) as database:
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(database.execute("SELECT value FROM sample").fetchone()[0], "restored")
            self.assertEqual((restored / "audio/1/sample.webm").read_bytes(), b"audio")
            self.assertEqual((restored / "material-assets/materials/1/photo.webp").read_bytes(), b"photo")
            self.assertEqual((restored / "assignment-assets/assignments/1/photo.webp").read_bytes(), b"snapshot")


if __name__ == "__main__":
    unittest.main()
