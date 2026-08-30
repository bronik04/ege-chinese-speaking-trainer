from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from trainer.services.review_request_repository import RequestMetadata, ReviewActor
from trainer.services.review_requests import ReviewRequestError, ReviewRequestService


class FakeReviewRequestRepository:
    def __init__(
        self,
        *,
        student_rows: list[dict] | None = None,
        teacher_rows: list[dict] | None = None,
        details: dict[int, dict] | None = None,
        custom_materials: dict[str, dict] | None = None,
    ):
        self.student_rows = student_rows or []
        self.teacher_rows = teacher_rows or []
        self.details = details or {}
        self.custom_materials = custom_materials or {}
        self.teacher_filters: dict | None = None
        self.requests: list[dict] = []
        self.items: list[dict] = []
        self.audits: list[dict] = []
        self.orphan_assignment_keys: list[str] = []

    def student_requests(self, student_id: int) -> list[dict]:
        return copy.deepcopy(self.student_rows)

    def teacher_requests(self, **filters) -> list[dict]:
        self.teacher_filters = filters
        return copy.deepcopy(self.teacher_rows)

    def teacher_detail(self, request_id: int) -> dict | None:
        return copy.deepcopy(self.details.get(request_id))

    @contextmanager
    def transaction(self, *, immediate: bool = False):
        before = copy.deepcopy((self.requests, self.items, self.audits))
        try:
            yield self
        except Exception:
            self.requests, self.items, self.audits = before
            raise

    def published_material(self, slug: str) -> dict | None:
        return copy.deepcopy(self.custom_materials.get(slug))

    def create_request(self, student_id: int, kind: str, variant_id: str, run_json: str) -> int:
        request_id = len(self.requests) + 1
        self.requests.append(
            {
                "id": request_id,
                "student_id": student_id,
                "kind": kind,
                "status": "uploading",
                "variant_id": variant_id,
                "run_json": run_json,
            }
        )
        return request_id

    def add_item(self, request_id: int, task: int, snapshot_json: str) -> int:
        item_id = len(self.items) + 1
        self.items.append({"id": item_id, "request_id": request_id, "task": task, "snapshot_json": snapshot_json})
        return item_id

    def audit(self, action: str, *, actor: ReviewActor, metadata: RequestMetadata, details: dict) -> None:
        self.audits.append({"action": action, "actor": actor, "metadata": metadata, "details": copy.deepcopy(details)})

    def enqueue_orphan_cleanup(self, *, audio_keys=(), assignment_keys=()) -> None:
        self.orphan_assignment_keys.extend(assignment_keys)

    def process_cleanup(self) -> None:
        return None


class ReviewRequestServiceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        variants = self.root / "content/variants"
        variants.mkdir(parents=True)
        (variants / "index.json").write_text("[]", encoding="utf-8")

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

    def test_create_persists_trimmed_snapshot_and_audit(self):
        repository = FakeReviewRequestRepository(
            custom_materials={
                "author-material": {
                    "id": "author-material",
                    "status": "published",
                    "tasks": {
                        "1": {"title": "Task 1"},
                        "2": {"title": "Task 2"},
                    },
                }
            }
        )

        result = self.make_service(repository).create(
            kind="task",
            tasks=[2],
            variant_id="author-material",
            run={"elapsed": 15},
            actor=ReviewActor(id=17, email="student@example.test"),
            metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
        )

        self.assertEqual(result, {"reviewRequest": {"id": 1, "status": "uploading"}})
        self.assertEqual(repository.requests[0]["status"], "uploading")
        self.assertEqual(json.loads(repository.requests[0]["run_json"]), {"elapsed": 15})
        self.assertEqual(json.loads(repository.items[0]["snapshot_json"]), {"title": "Task 2"})
        self.assertEqual(
            repository.audits,
            [
                {
                    "action": "review_request_created",
                    "actor": ReviewActor(id=17, email="student@example.test"),
                    "metadata": RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
                    "details": {"requestId": 1, "tasks": [2]},
                }
            ],
        )

    def test_create_rejects_oversized_run_without_persisting_state(self):
        repository = FakeReviewRequestRepository()

        with self.assertRaises(ReviewRequestError) as caught:
            self.make_service(repository).create(
                kind="task",
                tasks=[2],
                variant_id="author-material",
                run={"value": "x" * 100_001},
                actor=ReviewActor(id=17, email="student@example.test"),
                metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
            )

        self.assertEqual(caught.exception.reason, "run_too_large")
        self.assertEqual(repository.requests, [])

    def test_create_rejects_material_without_selected_task(self):
        repository = FakeReviewRequestRepository(
            custom_materials={"author-material": {"id": "author-material", "tasks": {"1": {}}}}
        )

        with self.assertRaises(ReviewRequestError) as caught:
            self.make_service(repository).create(
                kind="task",
                tasks=[2],
                variant_id="author-material",
                run={},
                actor=ReviewActor(id=17, email="student@example.test"),
                metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
            )

        self.assertEqual(caught.exception.reason, "invalid_material")
        self.assertEqual(repository.requests, [])


if __name__ == "__main__":
    unittest.main()
