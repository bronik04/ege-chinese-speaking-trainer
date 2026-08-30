from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from trainer.services.review_request_repository import (
    RecordingRow,
    RequestItem,
    RequestMetadata,
    ReviewActor,
    UploadTarget,
)
from trainer.services.review_requests import ReviewRequestError, ReviewRequestService


class FakeReviewRequestRepository:
    def __init__(
        self,
        *,
        student_rows: list[dict] | None = None,
        teacher_rows: list[dict] | None = None,
        details: dict[int, dict] | None = None,
        custom_materials: dict[str, dict] | None = None,
        upload_targets: dict[tuple[int, int, int], UploadTarget] | None = None,
        workflow_statuses: dict[tuple[int, int], str] | None = None,
        workflow_items: dict[int, list[RequestItem]] | None = None,
        uploaded_positions: dict[int, set[tuple[int, int | None]]] | None = None,
        storage_keys: dict[int, tuple[list[str], list[str]]] | None = None,
        scorable_items: dict[int, list[RequestItem]] | None = None,
    ):
        self.student_rows = student_rows or []
        self.teacher_rows = teacher_rows or []
        self.details = details or {}
        self.custom_materials = custom_materials or {}
        self.upload_targets = upload_targets or {}
        self.workflow_statuses = workflow_statuses or {}
        self.workflow_items = workflow_items or {}
        self.workflow_uploaded_positions = uploaded_positions or {}
        self.storage_keys = storage_keys or {}
        self.scorable = scorable_items or {}
        self.teacher_filters: dict | None = None
        self.requests: list[dict] = []
        self.items: list[dict] = []
        self.audits: list[dict] = []
        self.orphan_assignment_keys: list[str] = []
        self.orphan_audio_keys: list[str] = []
        self.recordings: list[dict] = []
        self.cleanup_audio_keys: list[str] = []
        self.cleanup_assignment_keys: list[str] = []
        self.saved_scores: list[dict] = []
        self.reviewed: dict[int, dict] = {}

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
        self.orphan_audio_keys.extend(audio_keys)
        self.orphan_assignment_keys.extend(assignment_keys)

    def process_cleanup(self) -> None:
        return None

    def upload_target(self, request_id: int, student_id: int, task: int) -> UploadTarget | None:
        return self.upload_targets.get((request_id, student_id, task))

    def guard_uploading(self, request_id: int, student_id: int) -> bool:
        return any(
            key[0] == request_id and key[1] == student_id and target.status == "uploading"
            for key, target in self.upload_targets.items()
        )

    def recordings_at(self, item_id: int, question: int | None) -> list[RecordingRow]:
        return [
            RecordingRow(row["id"], row["storage_key"])
            for row in self.recordings
            if row["item_id"] == item_id and row["question"] == question
        ]

    def remove_recordings_at(self, item_id: int, question: int | None) -> None:
        self.recordings = [
            row for row in self.recordings if not (row["item_id"] == item_id and row["question"] == question)
        ]

    def add_recording(self, **recording) -> int:
        recording_id = max((row["id"] for row in self.recordings), default=0) + 1
        self.recordings.append({"id": recording_id, **recording})
        return recording_id

    def enqueue_cleanup(self, *, audio_keys=(), assignment_keys=()) -> None:
        self.cleanup_audio_keys.extend(audio_keys)
        self.cleanup_assignment_keys.extend(assignment_keys)

    def request_status(self, request_id: int, student_id: int) -> str | None:
        return self.workflow_statuses.get((request_id, student_id))

    def request_items(self, request_id: int) -> list[RequestItem]:
        return copy.deepcopy(self.workflow_items.get(request_id, []))

    def uploaded_positions(self, request_id: int) -> set[tuple[int, int | None]]:
        return set(self.workflow_uploaded_positions.get(request_id, set()))

    def queue_request(self, request_id: int, student_id: int, submitted_at: int) -> bool:
        key = (request_id, student_id)
        if self.workflow_statuses.get(key) != "uploading":
            return False
        self.workflow_statuses[key] = "queued"
        return True

    def request_storage_keys(self, request_id: int) -> tuple[list[str], list[str]]:
        return copy.deepcopy(self.storage_keys.get(request_id, ([], [])))

    def delete_request(self, request_id: int, student_id: int) -> bool:
        return self.workflow_statuses.pop((request_id, student_id), None) is not None

    def scorable_items(self, request_id: int) -> list[RequestItem] | None:
        items = self.scorable.get(request_id)
        return copy.deepcopy(items) if items is not None else None

    def save_item_scores(self, item_id: int, scores_json: str, total: int, maximum: int) -> None:
        self.saved_scores.append({"item_id": item_id, "scores_json": scores_json, "total": total, "maximum": maximum})

    def mark_reviewed(self, request_id: int, reviewer_id: int, reviewed_at: int) -> None:
        self.reviewed[request_id] = {"reviewer_id": reviewer_id, "reviewed_at": reviewed_at}


class ReviewRequestServiceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        variants = self.root / "content/variants"
        variants.mkdir(parents=True)
        (variants / "index.json").write_text("[]", encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def make_service(
        self,
        repository: FakeReviewRequestRepository,
        *,
        duration_validator=None,
        max_audio_body: int = 15_000_000,
        clock=lambda: 1000,
    ) -> ReviewRequestService:
        return ReviewRequestService(
            repository,
            project_root=self.root,
            audio_root=self.root / "audio",
            material_asset_root=self.root / "material-assets",
            review_asset_root=self.root / "review-assets",
            temporary_root=self.root / "tmp",
            max_audio_body=max_audio_body,
            duration_validator=duration_validator or (lambda _path, _task: 1.0),
            clock=clock,
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

    def test_upload_replaces_recording_and_queues_old_storage_key(self):
        repository = FakeReviewRequestRepository(
            upload_targets={(9, 17, 2): UploadTarget(item_id=4, status="uploading")}
        )
        repository.recordings.append(
            {
                "id": 3,
                "item_id": 4,
                "question": None,
                "storage_key": "review-requests/9/old.webm",
            }
        )

        result = self.make_service(repository).upload_recording(
            request_id=9,
            task=2,
            question=None,
            label="Ответ",
            mime_type="audio/webm",
            body=b"new-audio",
            actor=ReviewActor(id=17, email="student@example.test"),
            metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
        )

        self.assertEqual(result, {"recording": {"id": 1}})
        self.assertEqual(len(repository.recordings), 1)
        self.assertEqual(repository.recordings[0]["item_id"], 4)
        self.assertEqual(repository.recordings[0]["duration_seconds"], 1.0)
        self.assertEqual(repository.cleanup_audio_keys, ["review-requests/9/old.webm"])
        stored_key = repository.recordings[0]["storage_key"]
        self.assertEqual((self.root / "audio" / stored_key).read_bytes(), b"new-audio")
        self.assertEqual(repository.audits[-1]["action"], "review_recording_uploaded")
        self.assertEqual(list((self.root / "tmp").glob("*")), [])

    def test_upload_rejects_unsupported_mime_before_writing_file(self):
        repository = FakeReviewRequestRepository(
            upload_targets={(9, 17, 2): UploadTarget(item_id=4, status="uploading")}
        )

        with self.assertRaises(ReviewRequestError) as caught:
            self.make_service(repository).upload_recording(
                request_id=9,
                task=2,
                question=None,
                label="Ответ",
                mime_type="audio/mpeg",
                body=b"audio",
                actor=ReviewActor(id=17, email="student@example.test"),
                metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
            )

        self.assertEqual(caught.exception.reason, "unsupported_media_type")
        self.assertFalse((self.root / "audio").exists())

    def test_upload_removes_temporary_file_when_audio_validation_fails(self):
        repository = FakeReviewRequestRepository(
            upload_targets={(9, 17, 2): UploadTarget(item_id=4, status="uploading")}
        )

        with self.assertRaises(ReviewRequestError) as caught:
            self.make_service(
                repository,
                duration_validator=lambda _path, _task: (_ for _ in ()).throw(ValueError("invalid")),
            ).upload_recording(
                request_id=9,
                task=2,
                question=None,
                label="Ответ",
                mime_type="audio/webm",
                body=b"audio",
                actor=ReviewActor(id=17, email="student@example.test"),
                metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
            )

        self.assertEqual(caught.exception.reason, "invalid_audio")
        self.assertEqual(list((self.root / "tmp").glob("*")), [])
        self.assertEqual(repository.recordings, [])

    def test_upload_persists_cleanup_intent_when_storage_write_fails(self):
        repository = FakeReviewRequestRepository(
            upload_targets={(9, 17, 2): UploadTarget(item_id=4, status="uploading")}
        )
        (self.root / "audio").write_bytes(b"blocks-storage-directory")

        with self.assertRaises(OSError):
            self.make_service(repository).upload_recording(
                request_id=9,
                task=2,
                question=None,
                label="Ответ",
                mime_type="audio/webm",
                body=b"audio",
                actor=ReviewActor(id=17, email="student@example.test"),
                metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
            )

        self.assertEqual(len(repository.orphan_audio_keys), 1)
        self.assertRegex(repository.orphan_audio_keys[0], r"^review-requests/9/.+\.webm$")
        self.assertEqual(list((self.root / "tmp").glob("*")), [])

    def test_complete_reports_exact_sorted_missing_positions(self):
        repository = FakeReviewRequestRepository(
            workflow_statuses={(9, 17): "uploading"},
            workflow_items={9: [RequestItem(1, 1), RequestItem(2, 2)]},
            uploaded_positions={9: {(1, 1), (1, 3), (1, 5)}},
        )

        with self.assertRaises(ReviewRequestError) as caught:
            self.make_service(repository).complete(
                9,
                actor=ReviewActor(id=17, email="student@example.test"),
                metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
            )

        self.assertEqual(caught.exception.reason, "incomplete")
        self.assertEqual(
            caught.exception.details["missing"],
            [{"task": 1, "question": 2}, {"task": 1, "question": 4}, {"task": 2}],
        )
        self.assertEqual(repository.workflow_statuses[(9, 17)], "uploading")

    def test_complete_queues_request_and_audits_tasks(self):
        repository = FakeReviewRequestRepository(
            workflow_statuses={(9, 17): "uploading"},
            workflow_items={9: [RequestItem(1, 2)]},
            uploaded_positions={9: {(2, None)}},
        )

        result = self.make_service(repository).complete(
            9,
            actor=ReviewActor(id=17, email="student@example.test"),
            metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
        )

        self.assertEqual(result, {"reviewRequest": {"id": 9, "status": "queued"}})
        self.assertEqual(repository.workflow_statuses[(9, 17)], "queued")
        self.assertEqual(repository.audits[-1]["details"], {"requestId": 9, "tasks": [2]})

    def test_discard_deletes_request_and_queues_all_private_keys(self):
        repository = FakeReviewRequestRepository(
            workflow_statuses={(9, 17): "uploading"},
            storage_keys={9: (["review-requests/9/audio.webm"], ["review-requests/9/image.webp"])},
        )

        result = self.make_service(repository).discard(
            9,
            actor=ReviewActor(id=17, email="student@example.test"),
            metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
        )

        self.assertEqual(result, {"ok": True})
        self.assertNotIn((9, 17), repository.workflow_statuses)
        self.assertEqual(repository.cleanup_audio_keys, ["review-requests/9/audio.webm"])
        self.assertEqual(repository.cleanup_assignment_keys, ["review-requests/9/image.webp"])
        self.assertEqual(repository.audits[-1]["action"], "review_request_discarded")

    def test_score_persists_normalized_scores_and_review_summary(self):
        repository = FakeReviewRequestRepository(scorable_items={9: [RequestItem(4, 2)]})

        result = self.make_service(repository).score(
            9,
            {"2": {"content": 3, "organization": 2, "language": 2}},
            actor=ReviewActor(id=99, email="teacher@example.test"),
            metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
        )

        self.assertEqual(
            result,
            {"reviewRequest": {"id": 9, "status": "reviewed", "total": 7, "maximum": 7}},
        )
        self.assertEqual(
            repository.saved_scores,
            [
                {
                    "item_id": 4,
                    "scores_json": '{"content":3,"organization":2,"language":2}',
                    "total": 7,
                    "maximum": 7,
                }
            ],
        )
        self.assertEqual(repository.reviewed[9], {"reviewer_id": 99, "reviewed_at": 1000})
        self.assertEqual(
            repository.audits[-1]["details"],
            {"requestId": 9, "tasks": [2], "total": 7, "maximum": 7},
        )

    def test_score_rejects_out_of_range_values_without_writes(self):
        repository = FakeReviewRequestRepository(scorable_items={9: [RequestItem(4, 2)]})

        with self.assertRaises(ReviewRequestError) as caught:
            self.make_service(repository).score(
                9,
                {"2": {"content": 4, "organization": 2, "language": 2}},
                actor=ReviewActor(id=99, email="teacher@example.test"),
                metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
            )

        self.assertEqual(caught.exception.reason, "invalid_scores")
        self.assertEqual(caught.exception.message, "Баллы за задание 2 выходят за допустимый диапазон")
        self.assertEqual(repository.saved_scores, [])


if __name__ == "__main__":
    unittest.main()
