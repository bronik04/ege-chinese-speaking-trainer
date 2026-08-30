from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from trainer.infrastructure.database.queries.review_requests import (
    review_request_detail,
    student_review_requests,
    teacher_review_requests,
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
