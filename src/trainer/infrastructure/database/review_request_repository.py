from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing, contextmanager
from pathlib import Path

from trainer.domain.materials import material_payload
from trainer.infrastructure.database.queries.review_requests import (
    review_request_detail,
    student_review_requests,
    teacher_review_requests,
)
from trainer.services import accounts as account_services
from trainer.services.review_request_repository import (
    MaterialAsset,
    RequestMetadata,
    ReviewActor,
)
from trainer.services.storage_cleanup import enqueue_cleanup_job, process_cleanup_jobs


class _SQLiteReviewRequestSession:
    def __init__(self, database: sqlite3.Connection):
        self.database = database

    def published_material(self, slug: str) -> dict | None:
        row = self.database.execute(
            "SELECT * FROM materials WHERE slug = ? AND status = 'published'", (slug,)
        ).fetchone()
        return material_payload(dict(row)) if row else None

    def create_request(self, student_id: int, kind: str, variant_id: str, run_json: str) -> int:
        return self.database.execute(
            """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json)
               VALUES (?,?,?,?,?)""",
            (student_id, kind, "uploading", variant_id, run_json),
        ).lastrowid

    def add_item(self, request_id: int, task: int, snapshot_json: str) -> int:
        return self.database.execute(
            """INSERT INTO review_request_items(request_id,task_number,task_snapshot_json)
               VALUES (?,?,?)""",
            (request_id, task, snapshot_json),
        ).lastrowid

    def material_asset(self, asset_id: int) -> MaterialAsset | None:
        row = self.database.execute(
            "SELECT storage_key,mime_type,size_bytes FROM material_assets WHERE id=?", (asset_id,)
        ).fetchone()
        return MaterialAsset(row["storage_key"], row["mime_type"], row["size_bytes"]) if row else None

    def add_review_asset(
        self,
        request_id: int,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        created_at: int,
    ) -> int:
        return self.database.execute(
            """INSERT INTO review_request_assets(request_id,storage_key,mime_type,size_bytes,created_at)
               VALUES (?,?,?,?,?)""",
            (request_id, storage_key, mime_type, size_bytes, created_at),
        ).lastrowid

    def remove_review_asset(self, asset_id: int) -> None:
        self.database.execute("DELETE FROM review_request_assets WHERE id=?", (asset_id,))

    def audit(
        self,
        action: str,
        *,
        actor: ReviewActor,
        metadata: RequestMetadata,
        details: Mapping[str, object],
    ) -> None:
        account_services.audit(
            self.database,
            action,
            client_ip=metadata.client_ip,
            user_agent=metadata.user_agent,
            user_id=actor.id,
            email=actor.email,
            details=dict(details),
        )


class SQLiteReviewRequestRepository:
    def __init__(
        self,
        connect_factory: Callable[[], sqlite3.Connection],
        *,
        audio_root: Path | None = None,
        material_root: Path | None = None,
        review_asset_root: Path | None = None,
    ):
        self._connect = connect_factory
        self.audio_root = audio_root
        self.material_root = material_root
        self.review_asset_root = review_asset_root

    @contextmanager
    def transaction(self, *, immediate: bool = False):
        with closing(self._connect()) as database:
            try:
                if immediate:
                    database.execute("BEGIN IMMEDIATE")
                yield _SQLiteReviewRequestSession(database)
                database.commit()
            except Exception:
                database.rollback()
                raise

    def student_requests(self, student_id: int) -> list[dict]:
        with closing(self._connect()) as database:
            return student_review_requests(database, student_id)

    def teacher_requests(
        self,
        *,
        student: str = "",
        task: int | None = None,
        status: str = "",
        submitted_from: int | None = None,
        submitted_before: int | None = None,
    ) -> list[dict]:
        with closing(self._connect()) as database:
            return teacher_review_requests(
                database,
                student=student,
                task=task,
                status=status,
                submitted_from=submitted_from,
                submitted_before=submitted_before,
            )

    def teacher_detail(self, request_id: int) -> dict | None:
        with closing(self._connect()) as database:
            return review_request_detail(database, request_id)

    def enqueue_orphan_cleanup(
        self,
        *,
        audio_keys: Sequence[str] = (),
        assignment_keys: Sequence[str] = (),
    ) -> None:
        with closing(self._connect()) as database:
            with database:
                enqueue_cleanup_job(
                    database,
                    audio_keys=audio_keys,
                    material_keys=[],
                    assignment_keys=assignment_keys,
                )

    def process_cleanup(self) -> None:
        if self.audio_root is None or self.material_root is None or self.review_asset_root is None:
            return
        with closing(self._connect()) as database:
            with database:
                process_cleanup_jobs(
                    database,
                    audio_root=self.audio_root,
                    material_root=self.material_root,
                    assignment_root=self.review_asset_root,
                )
