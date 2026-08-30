from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager

from trainer.services.material_repository import (
    MaterialAssetAccess,
    MaterialRecord,
)


def _material(row: sqlite3.Row) -> MaterialRecord:
    return MaterialRecord(
        id=row["id"],
        slug=row["slug"],
        owner_id=row["owner_id"],
        kind=row["kind"],
        task_number=row["task_number"],
        title=row["title"],
        year=row["year"],
        source=row["source"],
        status=row["status"],
        content_json=row["content_json"],
    )


class _SQLiteMaterialRepositorySession:
    def __init__(self, database: sqlite3.Connection):
        self.database = database


class SQLiteMaterialRepository:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self._connect = connect

    def published_materials(self) -> list[MaterialRecord]:
        with closing(self._connect()) as database:
            rows = database.execute(
                "SELECT * FROM materials WHERE status = 'published' ORDER BY year DESC, updated_at DESC"
            ).fetchall()
        return [_material(row) for row in rows]

    def owned_materials(self, owner_id: int) -> list[MaterialRecord]:
        with closing(self._connect()) as database:
            rows = database.execute(
                "SELECT * FROM materials WHERE owner_id = ? AND status != 'archived' ORDER BY updated_at DESC",
                (owner_id,),
            ).fetchall()
        return [_material(row) for row in rows]

    def material(self, slug: str) -> MaterialRecord | None:
        with closing(self._connect()) as database:
            row = database.execute("SELECT * FROM materials WHERE slug = ?", (slug,)).fetchone()
        return _material(row) if row else None

    def owned_material(self, slug: str, owner_id: int) -> MaterialRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT * FROM materials WHERE slug = ? AND owner_id = ?", (slug, owner_id)
            ).fetchone()
        return _material(row) if row else None

    def asset_access(self, asset_id: int) -> MaterialAssetAccess | None:
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT material_assets.storage_key,material_assets.mime_type,material_assets.size_bytes,
                          materials.owner_id,materials.status
                   FROM material_assets
                   JOIN materials ON materials.id=material_assets.material_id
                   WHERE material_assets.id=?""",
                (asset_id,),
            ).fetchone()
        return (
            MaterialAssetAccess(
                storage_key=row["storage_key"],
                mime_type=row["mime_type"],
                size_bytes=row["size_bytes"],
                owner_id=row["owner_id"],
                material_status=row["status"],
            )
            if row
            else None
        )

    @contextmanager
    def transaction(self) -> Iterator[_SQLiteMaterialRepositorySession]:
        database = self._connect()
        try:
            yield _SQLiteMaterialRepositorySession(database)
            database.commit()
        except BaseException:
            database.rollback()
            raise
        finally:
            database.close()
