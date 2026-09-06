from __future__ import annotations

import copy
import json
import secrets
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path

from trainer.domain.grading import CRITERIA, validate_scores
from trainer.domain.recording_retention import expires_at
from trainer.domain.review_requests import required_recording_positions, validate_review_selection
from trainer.services.materials import official_detail
from trainer.services.recordings import write_recording
from trainer.services.review_assets import copy_review_assets_from_roots
from trainer.services.review_request_repository import (
    RequestMetadata,
    ReviewActor,
    ReviewRequestRepository,
)


class ReviewRequestError(Exception):
    def __init__(self, reason: str, message: str = "", **details: object):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.details = details


class ReviewRequestService:
    def __init__(
        self,
        repository: ReviewRequestRepository,
        *,
        project_root: Path,
        audio_root: Path,
        material_asset_root: Path,
        review_asset_root: Path,
        temporary_root: Path,
        max_audio_body: int,
        duration_validator: Callable[[Path, int], float],
        clock: Callable[[], float] = time.time,
        cleanup_runner: Callable[[], object] = lambda: None,
    ):
        self.repository = repository
        self.project_root = project_root
        self.audio_root = audio_root
        self.material_asset_root = material_asset_root
        self.review_asset_root = review_asset_root
        self.temporary_root = temporary_root
        self.max_audio_body = max_audio_body
        self.duration_validator = duration_validator
        self.clock = clock
        self.cleanup_runner = cleanup_runner

    def student_requests(self, student_id: int) -> list[dict]:
        requests = copy.deepcopy(self.repository.student_requests(student_id))
        for request in requests:
            if request["status"] != "reviewed":
                request.pop("total", None)
                request.pop("maximum", None)
        return requests

    def teacher_requests(
        self,
        *,
        student: str = "",
        task: int | None = None,
        status: str = "",
        submitted_from: int | None = None,
        submitted_before: int | None = None,
    ) -> list[dict]:
        return copy.deepcopy(
            self.repository.teacher_requests(
                student=student,
                task=task,
                status=status,
                submitted_from=submitted_from,
                submitted_before=submitted_before,
            )
        )

    def teacher_detail(self, request_id: int) -> dict:
        detail = self.repository.teacher_detail(request_id)
        if detail is None:
            raise ReviewRequestError("not_found")
        return copy.deepcopy(detail)

    def create(
        self,
        *,
        kind: str,
        tasks: list[int],
        variant_id: str,
        run: object,
        actor: ReviewActor,
        metadata: RequestMetadata,
    ) -> dict:
        try:
            selection = validate_review_selection(kind, tasks)
        except ValueError as error:
            raise ReviewRequestError("invalid_request", str(error)) from error
        encoded_run = json.dumps(run, ensure_ascii=False, separators=(",", ":"))
        if len(encoded_run.encode("utf-8")) > 100_000:
            raise ReviewRequestError("run_too_large")

        created_asset_keys: list[str] = []
        try:
            with self.repository.transaction() as session:
                material = official_detail(self.project_root, variant_id) or session.published_material(variant_id)
                material_tasks = material.get("tasks", {}) if isinstance(material, dict) else {}
                if not material or any(str(task) not in material_tasks for task in selection.tasks):
                    raise ReviewRequestError("invalid_material")
                trimmed_material = {
                    **material,
                    "tasks": {str(task): material_tasks[str(task)] for task in selection.tasks},
                }
                request_id = session.create_request(actor.id, selection.kind, variant_id, encoded_run)
                snapshot = copy_review_assets_from_roots(
                    session,
                    request_id,
                    trimmed_material,
                    created_asset_keys,
                    material_asset_root=self.material_asset_root,
                    review_asset_root=self.review_asset_root,
                    public_root=self.project_root / "public",
                )
                for task in selection.tasks:
                    session.add_item(
                        request_id,
                        task,
                        json.dumps(snapshot["tasks"][str(task)], ensure_ascii=False, separators=(",", ":")),
                    )
                session.audit(
                    "review_request_created",
                    actor=actor,
                    metadata=metadata,
                    details={"requestId": request_id, "tasks": list(selection.tasks)},
                )
        except Exception:
            self._cleanup_orphans(assignment_keys=created_asset_keys)
            raise
        return {"reviewRequest": {"id": request_id, "status": "uploading"}}

    def _cleanup_orphans(self, *, audio_keys: list[str] | None = None, assignment_keys: list[str] | None = None):
        audio_keys = audio_keys or []
        assignment_keys = assignment_keys or []
        if not audio_keys and not assignment_keys:
            return
        with suppress(Exception):
            self.repository.enqueue_orphan_cleanup(
                audio_keys=audio_keys,
                assignment_keys=assignment_keys,
                now=int(self.clock()),
            )
            self.cleanup_runner()

    def upload_recording(
        self,
        *,
        request_id: int,
        task: int,
        question: int | None,
        label: str,
        mime_type: str,
        body: bytes,
        actor: ReviewActor,
        metadata: RequestMetadata,
    ) -> dict:
        extensions = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav"}
        if task not in {1, 2, 3} or mime_type not in extensions:
            raise ReviewRequestError("unsupported_media_type")
        if (task == 1 and question not in {1, 2, 3, 4, 5}) or (task in {2, 3} and question is not None):
            raise ReviewRequestError("invalid_request", "Некорректный номер записи")
        if not 0 < len(body) <= self.max_audio_body:
            raise ReviewRequestError("recording_too_large")

        with self.repository.transaction() as session:
            target = session.upload_target(request_id, actor.id, task)
        self._ensure_upload_target(target)

        storage_key = f"review-requests/{request_id}/{secrets.token_urlsafe(18)}.{extensions[mime_type]}"
        self.temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=self.temporary_root,
            suffix=f".{extensions[mime_type]}",
            delete=False,
        ) as file:
            file.write(body)
            temporary_path = Path(file.name)
        try:
            try:
                duration = self.duration_validator(temporary_path, task)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                raise ReviewRequestError("invalid_audio") from error

            try:
                write_recording(self.audio_root, storage_key, temporary_path, mime_type)
                with self.repository.transaction(immediate=True) as session:
                    current = session.upload_target(request_id, actor.id, task)
                    self._ensure_upload_target(current)
                    if not session.guard_uploading(request_id, actor.id):
                        raise ReviewRequestError("not_uploading")
                    replaced = session.recordings_at(current.item_id, question)
                    if replaced:
                        session.remove_recordings_at(current.item_id, question)
                    created_at = int(self.clock())
                    recording_id = session.add_recording(
                        item_id=current.item_id,
                        question=question,
                        label=label,
                        storage_key=storage_key,
                        mime_type=mime_type,
                        size_bytes=len(body),
                        duration_seconds=duration,
                        created_at=created_at,
                        expires_at=expires_at(created_at),
                    )
                    if replaced:
                        session.enqueue_cleanup(
                            audio_keys=[row.storage_key for row in replaced],
                            now=created_at,
                        )
                    session.audit(
                        "review_recording_uploaded",
                        actor=actor,
                        metadata=metadata,
                        details={"requestId": request_id, "task": task, "size": len(body)},
                    )
            except Exception:
                self._cleanup_orphans(audio_keys=[storage_key])
                raise
        finally:
            temporary_path.unlink(missing_ok=True)
        return {"recording": {"id": recording_id}}

    @staticmethod
    def _ensure_upload_target(target) -> None:
        if target is None:
            raise ReviewRequestError("not_found")
        if target.status != "uploading":
            raise ReviewRequestError("not_uploading")

    def complete(
        self,
        request_id: int,
        *,
        actor: ReviewActor,
        metadata: RequestMetadata,
    ) -> dict:
        with self.repository.transaction(immediate=True) as session:
            self._ensure_uploading_status(session.request_status(request_id, actor.id))
            items = session.request_items(request_id)
            tasks = [item.task for item in items]
            missing = sorted(
                required_recording_positions(tasks) - session.uploaded_positions(request_id),
                key=lambda item: (item[0], item[1] or 0),
            )
            if missing:
                raise ReviewRequestError(
                    "incomplete",
                    missing=[
                        {"task": task, **({"question": question} if question is not None else {})}
                        for task, question in missing
                    ],
                )
            if not session.queue_request(request_id, actor.id, int(self.clock())):
                raise ReviewRequestError("not_uploading")
            session.audit(
                "review_request_queued",
                actor=actor,
                metadata=metadata,
                details={"requestId": request_id, "tasks": tasks},
            )
        return {"reviewRequest": {"id": request_id, "status": "queued"}}

    def discard(
        self,
        request_id: int,
        *,
        actor: ReviewActor,
        metadata: RequestMetadata,
    ) -> dict:
        now = int(self.clock())
        with self.repository.transaction(immediate=True) as session:
            self._ensure_uploading_status(session.request_status(request_id, actor.id))
            audio_keys, assignment_keys = session.request_storage_keys(request_id)
            if not session.delete_request(request_id, actor.id):
                raise ReviewRequestError("not_found")
            if audio_keys or assignment_keys:
                session.enqueue_cleanup(
                    audio_keys=audio_keys,
                    assignment_keys=assignment_keys,
                    now=now,
                )
            session.audit(
                "review_request_discarded",
                actor=actor,
                metadata=metadata,
                details={"requestId": request_id},
            )
        with suppress(Exception):
            self.cleanup_runner()
        return {"ok": True}

    @staticmethod
    def _ensure_uploading_status(status: str | None) -> None:
        if status is None:
            raise ReviewRequestError("not_found")
        if status != "uploading":
            raise ReviewRequestError("not_uploading")

    def score(
        self,
        request_id: int,
        scores_payload: Mapping[str, object],
        *,
        actor: ReviewActor,
        metadata: RequestMetadata,
    ) -> dict:
        with self.repository.transaction() as session:
            items = session.scorable_items(request_id)
            if items is None:
                raise ReviewRequestError("not_found")
            tasks = [item.task for item in items]
            try:
                scores, total, maximum = validate_scores(scores_payload, tasks)
            except ValueError as error:
                raise ReviewRequestError("invalid_scores", str(error)) from error
            for item in items:
                task_scores = scores[str(item.task)]
                session.save_item_scores(
                    item.id,
                    json.dumps(task_scores, ensure_ascii=False, separators=(",", ":")),
                    sum(task_scores.values()),
                    sum(CRITERIA[item.task].values()),
                )
            session.mark_reviewed(request_id, actor.id, int(self.clock()))
            session.audit(
                "review_request_scored",
                actor=actor,
                metadata=metadata,
                details={"requestId": request_id, "tasks": tasks, "total": total, "maximum": maximum},
            )
        return {
            "reviewRequest": {
                "id": request_id,
                "status": "reviewed",
                "total": total,
                "maximum": maximum,
            }
        }
