from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from trainer.domain.review_requests import validate_review_selection
from trainer.services.materials import official_detail
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
            self.repository.enqueue_orphan_cleanup(audio_keys=audio_keys, assignment_keys=assignment_keys)
            self.repository.process_cleanup()
