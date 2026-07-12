from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from trainer.config import PROJECT_ROOT
from trainer.infrastructure.database.sqlite_migrations import MIGRATIONS, apply_migrations

BASELINE_REVISION = "20260711_03"
BASELINE_VERSIONS = (1, 2, 3, 4, 5, 6, 7)


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", normalize_database_url(database_url).replace("%", "%%"))
    return config


def upgrade_database(database_url: str) -> None:
    normalized = normalize_database_url(database_url)
    if not normalized.startswith("postgresql+"):
        command.upgrade(_config(database_url), "head")
        return
    engine = create_engine(normalized)
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(2026071204)"))
            config = _config(database_url)
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def head_revision() -> str:
    return ScriptDirectory.from_config(_config("sqlite://")).get_current_head()


def current_revision(database_url: str) -> str | None:
    engine = create_engine(normalize_database_url(database_url))
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def apply_sqlite_baseline(database: sqlite3.Connection) -> None:
    configured_versions = tuple(version for version, _ in MIGRATIONS)
    if configured_versions != BASELINE_VERSIONS:
        raise RuntimeError(
            "SQLite legacy migrations are frozen at versions 1-7; add new schema changes through Alembic"
        )
    apply_migrations(database)


def upgrade_sqlite_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as database:
        database.row_factory = sqlite3.Row
        with database:
            apply_sqlite_baseline(database)
            applied = tuple(
                row["version"] for row in database.execute("SELECT version FROM schema_migrations ORDER BY version")
            )
            if applied != BASELINE_VERSIONS:
                raise RuntimeError(
                    f"SQLite compatibility baseline mismatch: expected {BASELINE_VERSIONS}, got {applied}"
                )
            has_alembic_version = database.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()

    database_url = sqlite_url(path)
    if not has_alembic_version:
        command.stamp(_config(database_url), BASELINE_REVISION)
    upgrade_database(database_url)
