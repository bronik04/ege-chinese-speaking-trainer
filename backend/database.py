from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from backend.migrations import apply_migrations


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(data_dir: Path, audio_dir: Path, database_path: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as database:
        apply_migrations(database)
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
