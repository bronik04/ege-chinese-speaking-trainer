from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from trainer.services.review_requests import ReviewRequestError, ReviewRequestService


class FakeReviewRequestRepository:
    def __init__(
        self,
        *,
        student_rows: list[dict] | None = None,
        teacher_rows: list[dict] | None = None,
        details: dict[int, dict] | None = None,
    ):
        self.student_rows = student_rows or []
        self.teacher_rows = teacher_rows or []
        self.details = details or {}
        self.teacher_filters: dict | None = None

    def student_requests(self, student_id: int) -> list[dict]:
        return copy.deepcopy(self.student_rows)

    def teacher_requests(self, **filters) -> list[dict]:
        self.teacher_filters = filters
        return copy.deepcopy(self.teacher_rows)

    def teacher_detail(self, request_id: int) -> dict | None:
        return copy.deepcopy(self.details.get(request_id))


class ReviewRequestServiceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def make_service(self, repository: FakeReviewRequestRepository) -> ReviewRequestService:
        return ReviewRequestService(
            repository,
            project_root=self.root,
            audio_root=self.root / "audio",
            material_asset_root=self.root / "material-assets",
            review_asset_root=self.root / "review-assets",
            temporary_root=self.root / "tmp",
            max_audio_body=15_000_000,
            duration_validator=lambda _path, _task: 1.0,
        )

    def test_student_list_hides_totals_until_reviewed(self):
        repository = FakeReviewRequestRepository(
            student_rows=[
                {"id": 1, "status": "uploading", "total": 4, "maximum": 7},
                {"id": 2, "status": "reviewed", "total": 6, "maximum": 7},
            ]
        )

        rows = self.make_service(repository).student_requests(17)

        self.assertNotIn("total", rows[0])
        self.assertNotIn("maximum", rows[0])
        self.assertEqual((rows[1]["total"], rows[1]["maximum"]), (6, 7))
        self.assertEqual(repository.student_rows[0]["total"], 4)

    def test_error_is_semantic_and_keeps_details(self):
        error = ReviewRequestError("incomplete", missing=[{"task": 1, "question": 2}])

        self.assertEqual(error.reason, "incomplete")
        self.assertEqual(error.details, {"missing": [{"task": 1, "question": 2}]})
        self.assertFalse(hasattr(error, "status"))

    def test_teacher_list_preserves_parsed_filters(self):
        repository = FakeReviewRequestRepository(teacher_rows=[{"id": 9, "status": "queued"}])

        rows = self.make_service(repository).teacher_requests(
            student="student@example.test",
            task=2,
            status="queued",
            submitted_from=100,
            submitted_before=200,
        )

        self.assertEqual(rows, [{"id": 9, "status": "queued"}])
        self.assertEqual(
            repository.teacher_filters,
            {
                "student": "student@example.test",
                "task": 2,
                "status": "queued",
                "submitted_from": 100,
                "submitted_before": 200,
            },
        )

    def test_teacher_detail_returns_copy_of_repository_data(self):
        repository = FakeReviewRequestRepository(details={9: {"id": 9, "material": {"2": {"title": "Task"}}}})

        detail = self.make_service(repository).teacher_detail(9)
        detail["material"]["2"]["title"] = "Changed"

        self.assertEqual(repository.details[9]["material"]["2"]["title"], "Task")

    def test_teacher_detail_rejects_missing_request(self):
        with self.assertRaises(ReviewRequestError) as caught:
            self.make_service(FakeReviewRequestRepository()).teacher_detail(404)

        self.assertEqual(caught.exception.reason, "not_found")


if __name__ == "__main__":
    unittest.main()
