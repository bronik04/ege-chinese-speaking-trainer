from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from scripts.backup import create_backup


def database_url(base_url: str, name: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{name}", parsed.query, parsed.fragment))


def main() -> None:
    source_url = os.environ["TEST_DATABASE_URL"]
    restore_name = "trainer_restore_test"
    admin_url = database_url(source_url, "postgres")
    restore_url = database_url(source_url, restore_name)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "backups"
        output.mkdir()
        backup = create_backup(Path(directory), output, 1, source_url, "s3") / "trainer.pgdump"
        with psycopg.connect(admin_url, autocommit=True) as database:
            database.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(restore_name)))
            database.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_name)))
        try:
            subprocess.run(["pg_restore", "--no-owner", f"--dbname={restore_url}", str(backup)], check=True)
            with psycopg.connect(restore_url) as database:
                tables = database.execute(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
                ).fetchone()[0]
                if tables < 10:
                    raise RuntimeError("Restored PostgreSQL schema is incomplete")
        finally:
            with psycopg.connect(admin_url, autocommit=True) as database:
                database.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(restore_name))
                )


if __name__ == "__main__":
    main()
