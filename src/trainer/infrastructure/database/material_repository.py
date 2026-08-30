from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager

from trainer.infrastructure.database.core import INTEGRITY_ERRORS
from trainer.services import accounts as account_services
from trainer.services.material_repository import (
    MaterialAssetAccess,
    MaterialAudit,
    MaterialConflictError,
    MaterialRecord,
    MaterialRequestData,
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

    def create(self, owner_id: int, data: MaterialRequestData, now: int) -> int:
        try:
            return self.database.execute(
                """INSERT INTO materials
                   (slug,owner_id,kind,task_number,title,year,source,status,content_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,'draft',?,?,?)""",
                (
                    data.slug,
                    owner_id,
                    data.kind,
                    data.task_number,
                    data.title,
                    data.year,
                    data.source,
                    json.dumps(data.content, ensure_ascii=False),
                    now,
                    now,
                ),
            ).lastrowid
        except INTEGRITY_ERRORS as error:
            raise MaterialConflictError from error

    def update(
        self,
        current_slug: str,
        owner_id: int,
        data: MaterialRequestData,
        now: int,
    ) -> bool:
        try:
            cursor = self.database.execute(
                """UPDATE materials SET slug=?,kind=?,task_number=?,title=?,year=?,source=?,content_json=?,
                       status='draft',published_at=NULL,updated_at=? WHERE slug=? AND owner_id=?""",
                (
                    data.slug,
                    data.kind,
                    data.task_number,
                    data.title,
                    data.year,
                    data.source,
                    json.dumps(data.content, ensure_ascii=False),
                    now,
                    current_slug,
                    owner_id,
                ),
            )
        except INTEGRITY_ERRORS as error:
            raise MaterialConflictError from error
        return bool(cursor.rowcount)

    def audit(self, event: MaterialAudit) -> None:
        account_services.audit(
            self.database,
            event.action,
            client_ip=event.metadata.client_ip,
            user_agent=event.metadata.user_agent,
            user_id=event.actor.id,
            email=event.actor.email,
            details=dict(event.details),
        )


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
