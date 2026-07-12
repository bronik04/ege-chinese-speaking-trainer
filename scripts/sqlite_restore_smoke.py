from __future__ import annotations

import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path

from scripts.backup import create_backup


def _extract_archive(archive_path: Path, target: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        target_root = target.resolve()
        for member in archive.getmembers():
            destination = (target / member.name).resolve()
            if destination != target_root and target_root not in destination.parents:
                raise RuntimeError(f"Unsafe backup archive member: {member.name}")
        archive.extractall(target, filter="data")


def restore_sqlite_backup(backup: Path, target: Path) -> None:
    database_backup = backup / "trainer.sqlite3"
    archives = (
        backup / "audio.tar.gz",
        backup / "material-assets.tar.gz",
        backup / "assignment-assets.tar.gz",
    )
    missing = [path.name for path in (database_backup, *archives) if not path.is_file()]
    if missing:
        raise RuntimeError(f"Incomplete SQLite backup: {', '.join(missing)}")
    if target.exists() and any(target.iterdir()):
        raise RuntimeError(f"Restore target is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(database_backup, target / "trainer.sqlite3")
    for archive in archives:
        _extract_archive(archive, target)
    with closing(sqlite3.connect(target / "trainer.sqlite3")) as database:
        if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Restored SQLite database failed integrity check")


def run_smoke() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        data = root / "data"
        backups = root / "backups"
        restored = root / "restored"
        (data / "audio/1").mkdir(parents=True)
        (data / "audio/1/sample.webm").write_bytes(b"audio-smoke")
        (data / "material-assets/materials/1").mkdir(parents=True)
        (data / "material-assets/materials/1/photo.webp").write_bytes(b"asset-smoke")
        (data / "assignment-assets/assignments/1").mkdir(parents=True)
        (data / "assignment-assets/assignments/1/photo.webp").write_bytes(b"snapshot-smoke")
        with closing(sqlite3.connect(data / "trainer.sqlite3")) as database:
            with database:
                database.execute("CREATE TABLE smoke(value TEXT NOT NULL)")
                database.execute("INSERT INTO smoke VALUES ('restored')")
        backups.mkdir()
        backup = create_backup(data, backups, 1)
        restore_sqlite_backup(backup, restored)
        with closing(sqlite3.connect(restored / "trainer.sqlite3")) as database:
            if database.execute("SELECT value FROM smoke").fetchone()[0] != "restored":
                raise RuntimeError("Restored SQLite data does not match source")
        if (restored / "audio/1/sample.webm").read_bytes() != b"audio-smoke":
            raise RuntimeError("Restored audio does not match source")
        if (restored / "material-assets/materials/1/photo.webp").read_bytes() != b"asset-smoke":
            raise RuntimeError("Restored material asset does not match source")
        if (restored / "assignment-assets/assignments/1/photo.webp").read_bytes() != b"snapshot-smoke":
            raise RuntimeError("Restored assignment asset does not match source")


def main() -> None:
    run_smoke()
    print("SQLite backup restore smoke passed")


if __name__ == "__main__":
    main()
