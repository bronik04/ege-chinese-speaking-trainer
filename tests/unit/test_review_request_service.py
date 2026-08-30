from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from trainer.services.review_requests import ReviewRequestError, ReviewRequestService


class FakeReviewRequestRepository:
    def __init__(self, *, student_rows: list[dict] | None = None):
        self.student_rows = student_rows or []

    def student_requests(self, student_id: int) -> list[dict]:
        return copy.deepcopy(self.student_rows)


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


if __name__ == "__main__":
    unittest.main()
