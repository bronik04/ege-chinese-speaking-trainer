from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from trainer.infrastructure.database.migrations import upgrade_sqlite_database


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(path: Path) -> sqlite3.Connection:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        from trainer.infrastructure.database.postgres import connect as postgres_connect

        return postgres_connect(database_url)
    connection = sqlite3.connect(path, timeout=10, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(data_dir: Path, audio_dir: Path, database_path: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        from trainer.infrastructure.database.postgres import initialize as initialize_postgres

        initialize_postgres(database_url)
    else:
        upgrade_sqlite_database(database_path)
    with connect(database_path) as database:
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        database.execute("DELETE FROM account_tokens WHERE expires_at <= ?", (int(time.time()),))
        database.execute("DELETE FROM auth_rate_limits WHERE updated_at <= ?", (int(time.time()) - 30 * 86400,))


def engine_name() -> str:
    return "postgresql" if os.environ.get("DATABASE_URL", "").strip() else "sqlite"


def close_connections() -> None:
    if os.environ.get("DATABASE_URL", "").strip():
        from trainer.infrastructure.database.postgres import close_pools

        close_pools()


try:
    import psycopg

    INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)
except ImportError:
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)
