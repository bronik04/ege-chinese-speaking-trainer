from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from trainer.infrastructure.database.migrations import upgrade_sqlite_database

INTEGRITY_ERRORS = sqlite3.IntegrityError


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
    # WAL включаем на каждом соединении: режим журнала хранится в файле базы,
    # но повторная установка дешёвая и снимает зависимость от порядка запуска.
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize(data_dir: Path, audio_dir: Path, database_path: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    upgrade_sqlite_database(database_path)
    with connect(database_path) as database:
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        database.execute("DELETE FROM account_tokens WHERE expires_at <= ?", (int(time.time()),))
        database.execute("DELETE FROM auth_rate_limits WHERE updated_at <= ?", (int(time.time()) - 30 * 86400,))
