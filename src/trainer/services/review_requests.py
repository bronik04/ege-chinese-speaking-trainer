from __future__ import annotations

import copy
import time
from collections.abc import Callable
from pathlib import Path

from trainer.services.review_request_repository import ReviewRequestRepository


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
