from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing, contextmanager
from pathlib import Path

from trainer.domain.materials import material_payload
from trainer.infrastructure.database.accounts import record_audit
from trainer.infrastructure.database.core import begin_immediate
from trainer.infrastructure.database.queries.review_requests import (
    review_request_detail,
    student_review_requests,
    teacher_review_requests,
)
from trainer.services.review_request_repository import (
    MaterialAsset,
    RecordingRow,
    RequestItem,
    RequestMetadata,
    ReviewActor,
    UploadTarget,
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
        record_audit(
            self.database,
            action,
            ip_address=metadata.client_ip,
            user_agent=metadata.user_agent,
            user_id=actor.id,
            email=actor.email,
            details=dict(details),
        )

    def upload_target(self, request_id: int, student_id: int, task: int) -> UploadTarget | None:
        row = self.database.execute(
            """SELECT review_request_items.id,review_requests.status
               FROM review_request_items
               JOIN review_requests ON review_requests.id=review_request_items.request_id
               WHERE review_requests.id=? AND review_requests.student_id=? AND review_request_items.task_number=?""",
            (request_id, student_id, task),
        ).fetchone()
        return UploadTarget(row["id"], row["status"]) if row else None

    def guard_uploading(self, request_id: int, student_id: int) -> bool:
        cursor = self.database.execute(
            """UPDATE review_requests SET status='uploading'
               WHERE id=? AND student_id=? AND status='uploading'""",
            (request_id, student_id),
        )
        return bool(cursor.rowcount)

    def recordings_at(self, item_id: int, question: int | None) -> list[RecordingRow]:
        rows = self.database.execute(
            """SELECT id,storage_key FROM review_request_recordings
               WHERE item_id=? AND question_number IS ?""",
            (item_id, question),
        ).fetchall()
        return [RecordingRow(row["id"], row["storage_key"]) for row in rows]

    def remove_recordings_at(self, item_id: int, question: int | None) -> None:
        self.database.execute(
            "DELETE FROM review_request_recordings WHERE item_id=? AND question_number IS ?",
            (item_id, question),
        )

    def add_recording(
        self,
        *,
        item_id: int,
        question: int | None,
        label: str,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        duration_seconds: float,
        created_at: int,
        expires_at: int,
    ) -> int:
        return self.database.execute(
            """INSERT INTO review_request_recordings
               (item_id,question_number,label,storage_key,mime_type,size_bytes,duration_seconds,created_at,expires_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                item_id,
                question,
                label,
                storage_key,
                mime_type,
                size_bytes,
                duration_seconds,
                created_at,
                expires_at,
            ),
        ).lastrowid

    def enqueue_cleanup(
        self,
        *,
        audio_keys: Sequence[str] = (),
        assignment_keys: Sequence[str] = (),
    ) -> None:
        enqueue_cleanup_job(
            self.database,
            audio_keys=audio_keys,
            material_keys=[],
            assignment_keys=assignment_keys,
        )

    def request_status(self, request_id: int, student_id: int) -> str | None:
        row = self.database.execute(
            "SELECT status FROM review_requests WHERE id=? AND student_id=?",
            (request_id, student_id),
        ).fetchone()
        return row["status"] if row else None

    def request_items(self, request_id: int) -> list[RequestItem]:
        rows = self.database.execute(
            "SELECT id,task_number FROM review_request_items WHERE request_id=? ORDER BY task_number",
            (request_id,),
        ).fetchall()
        return [RequestItem(row["id"], row["task_number"]) for row in rows]

    def uploaded_positions(self, request_id: int) -> set[tuple[int, int | None]]:
        rows = self.database.execute(
            """SELECT review_request_items.task_number,review_request_recordings.question_number
               FROM review_request_recordings
               JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
               WHERE review_request_items.request_id=?""",
            (request_id,),
        ).fetchall()
        return {(row["task_number"], row["question_number"]) for row in rows}

    def queue_request(self, request_id: int, student_id: int, submitted_at: int) -> bool:
        cursor = self.database.execute(
            """UPDATE review_requests SET status='queued',submitted_at=?
               WHERE id=? AND student_id=? AND status='uploading'""",
            (submitted_at, request_id, student_id),
        )
        return bool(cursor.rowcount)

    def request_storage_keys(self, request_id: int) -> tuple[list[str], list[str]]:
        audio_keys = [
            row["storage_key"]
            for row in self.database.execute(
                """SELECT review_request_recordings.storage_key FROM review_request_recordings
                   JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
                   WHERE review_request_items.request_id=?""",
                (request_id,),
            ).fetchall()
        ]
        assignment_keys = [
            row["storage_key"]
            for row in self.database.execute(
                "SELECT storage_key FROM review_request_assets WHERE request_id=?",
                (request_id,),
            ).fetchall()
        ]
        return audio_keys, assignment_keys

    def delete_request(self, request_id: int, student_id: int) -> bool:
        cursor = self.database.execute(
            "DELETE FROM review_requests WHERE id=? AND student_id=?",
            (request_id, student_id),
        )
        return bool(cursor.rowcount)

    def scorable_items(self, request_id: int) -> list[RequestItem] | None:
        request = self.database.execute(
            "SELECT id FROM review_requests WHERE id=? AND status IN ('queued','reviewed')",
            (request_id,),
        ).fetchone()
        if not request:
            return None
        return self.request_items(request_id)

    def save_item_scores(self, item_id: int, scores_json: str, total: int, maximum: int) -> None:
        self.database.execute(
            """UPDATE review_request_items
               SET scores_json=?,total_score=?,max_score=? WHERE id=?""",
            (scores_json, total, maximum, item_id),
        )

    def mark_reviewed(self, request_id: int, reviewer_id: int, reviewed_at: int) -> None:
        self.database.execute(
            """UPDATE review_requests
               SET status='reviewed',reviewed_at=?,reviewer_id=? WHERE id=?""",
            (reviewed_at, reviewer_id, request_id),
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
                    begin_immediate(database)
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
