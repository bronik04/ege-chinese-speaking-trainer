from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from trainer.infrastructure.database.migrations import (
    BASELINE_REVISION,
    apply_sqlite_baseline,
    upgrade_sqlite_database,
)

EXPECTED_TABLES = {
    "account_tokens",
    "assignments",
    "audit_log",
    "auth_rate_limits",
    "group_members",
    "material_assets",
    "materials",
    "recordings",
    "reviews",
    "sessions",
    "study_groups",
    "submissions",
    "transcription_jobs",
    "user_progress",
    "users",
}


def sqlite_schema(path: Path) -> tuple[set[str], set[str]]:
    with closing(sqlite3.connect(path)) as database:
        tables = {
            row[0]
            for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("sqlite_") and row[0] not in {"alembic_version", "schema_migrations"}
        }
        indexes = {
            row[0]
            for row in database.execute("SELECT name FROM sqlite_master WHERE type='index'")
            if not row[0].startswith("sqlite_autoindex_")
        }
    return tables, indexes


class SqliteMigrationTest(unittest.TestCase):
    def test_legacy_baseline_rejects_new_sqlite_migration(self):
        from trainer.infrastructure.database import migrations

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                extended = [*migrations.MIGRATIONS, (8, lambda connection: None)]
                with patch.object(migrations, "MIGRATIONS", extended):
                    with self.assertRaisesRegex(RuntimeError, "frozen"):
                        apply_sqlite_baseline(database)

    def test_clean_database_gets_baseline_and_alembic_head(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                versions = [
                    row[0] for row in database.execute("SELECT version FROM schema_migrations ORDER BY version")
                ]
                revision = database.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            self.assertEqual(versions, list(range(1, 8)))
            self.assertEqual(revision, BASELINE_REVISION)
            self.assertEqual(sqlite_schema(path)[0], EXPECTED_TABLES)

    def test_existing_legacy_database_is_stamped_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            with closing(sqlite3.connect(path)) as database:
                database.row_factory = sqlite3.Row
                with database:
                    apply_sqlite_baseline(database)
                    database.execute(
                        "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                        ("kept@example.test", "hash", "Kept", "student", 1),
                    )
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                email = database.execute("SELECT email FROM users").fetchone()[0]
                revision = database.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            self.assertEqual(email, "kept@example.test")
            self.assertEqual(revision, BASELINE_REVISION)

    def test_repeated_upgrade_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(path)
            before = sqlite_schema(path)
            upgrade_sqlite_database(path)
            self.assertEqual(sqlite_schema(path), before)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class PostgresMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg

        cls.url = os.environ["TEST_DATABASE_URL"]
        with psycopg.connect(cls.url, autocommit=True) as database:
            database.execute("DROP SCHEMA public CASCADE")
            database.execute("CREATE SCHEMA public")

    def test_postgres_upgrade_is_idempotent_and_reaches_head(self):
        from trainer.infrastructure.database.migrations import current_revision, head_revision, upgrade_database

        upgrade_database(self.url)
        upgrade_database(self.url)
        self.assertEqual(current_revision(self.url), head_revision())

    def test_postgres_and_sqlite_have_matching_tables_columns_and_indexes(self):
        import psycopg

        from trainer.infrastructure.database.migrations import upgrade_database

        upgrade_database(self.url)
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = Path(directory) / "trainer.sqlite3"
            upgrade_sqlite_database(sqlite_path)
            with closing(sqlite3.connect(sqlite_path)) as database:
                sqlite_columns = {
                    (table, row[1])
                    for table in EXPECTED_TABLES
                    for row in database.execute(f"PRAGMA table_info({table})")
                }
                sqlite_indexes = sqlite_schema(sqlite_path)[1]

        with psycopg.connect(self.url) as database:
            postgres_tables = {
                row[0]
                for row in database.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                )
                if row[0] not in {"alembic_version", "schema_migrations"}
            }
            postgres_columns = set(
                database.execute(
                    "SELECT table_name,column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name NOT IN ('alembic_version','schema_migrations')"
                ).fetchall()
            )
            postgres_indexes = {
                row[0]
                for row in database.execute(
                    "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname NOT LIKE '%_pkey'"
                )
                if not row[0].endswith("_key")
            }

        self.assertEqual(postgres_tables, EXPECTED_TABLES)
        self.assertEqual(postgres_columns, sqlite_columns)
        self.assertEqual(postgres_indexes, sqlite_indexes)


if __name__ == "__main__":
    unittest.main()
