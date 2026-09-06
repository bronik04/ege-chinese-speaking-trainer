from __future__ import annotations

import unittest

from trainer.services.storage_cleanup import CleanupSummary, StorageCleanupService
from trainer.services.storage_cleanup_repository import (
    ClaimedCleanupJob,
    CleanupBatchResult,
    CleanupKeys,
    CleanupOutcome,
)


class FakeStorageCleanupRepository:
    def __init__(self):
        self.expired = 0
        self.jobs: list[ClaimedCleanupJob] = []
        self.result = CleanupBatchResult()
        self.pending = 0
        self.expire_calls: list[dict] = []
        self.claim_calls: list[dict] = []
        self.finish_calls: list[tuple[list[CleanupOutcome], dict]] = []

    def expire_recordings(self, **kwargs) -> int:
        self.expire_calls.append(kwargs)
        return self.expired

    def claim_jobs(self, **kwargs) -> list[ClaimedCleanupJob]:
        self.claim_calls.append(kwargs)
        return self.jobs

    def finish_jobs(self, outcomes, **kwargs) -> CleanupBatchResult:
        self.finish_calls.append((list(outcomes), kwargs))
        return self.result

    def pending_jobs(self) -> int:
        return self.pending


class RecordingStorage:
    def __init__(self, failures=()):
        self.deleted: list[str] = []
        self.failures = set(failures)

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        if key == "missing":
            raise FileNotFoundError(key)
        if key in self.failures:
            raise OSError(f"cannot delete {key}")


class StorageFactory:
    def __init__(self, storage=None, error: Exception | None = None):
        self.storage = storage or RecordingStorage()
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.storage


class StorageCleanupServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = FakeStorageCleanupRepository()
        self.audio = RecordingStorage()
        self.material = RecordingStorage()
        self.assignment = RecordingStorage()
        self.audio_factory = StorageFactory(self.audio)
        self.material_factory = StorageFactory(self.material)
        self.assignment_factory = StorageFactory(self.assignment)
        self.service = StorageCleanupService(
            self.repository,
            audio_storage=self.audio_factory,
            material_storage=self.material_factory,
            assignment_storage=self.assignment_factory,
            clock=lambda: 100,
        )

    def test_expire_batch_delegates_normalized_limit_and_time(self):
        self.repository.expired = 2

        self.assertEqual(self.service.expire_batch(limit=-1, now=90), 2)

        self.assertEqual(self.repository.expire_calls, [{"now": 90, "limit": 0}])

    def test_processes_every_category_and_treats_missing_as_success(self):
        self.repository.jobs = [
            ClaimedCleanupJob(
                7,
                CleanupKeys(("audio", "missing"), ("material",), ("assignment",)),
                3700,
            )
        ]
        self.repository.result = CleanupBatchResult(completed=1)

        result = self.service.process_batch()

        self.assertEqual(result, CleanupSummary(completed=1))
        self.assertEqual(self.audio.deleted, ["audio", "missing"])
        self.assertEqual(self.material.deleted, ["material"])
        self.assertEqual(self.assignment.deleted, ["assignment"])
        self.assertEqual(self.repository.claim_calls, [{"now": 100, "lease_until": 3700, "limit": 50}])
        outcomes, finish_arguments = self.repository.finish_calls[0]
        self.assertEqual(outcomes, [CleanupOutcome(7)])
        self.assertEqual(finish_arguments, {"lease_until": 3700, "now": 100, "retry_at": 3700})

    def test_attempts_every_key_and_records_only_the_first_failure(self):
        self.audio.failures = {"first", "second"}
        self.repository.jobs = [ClaimedCleanupJob(8, CleanupKeys(audio=("first", "second", "last")), 3700)]
        self.repository.result = CleanupBatchResult(failed=1, pending=1)

        result = self.service.process_batch()

        self.assertEqual(result, CleanupSummary(failed=1, pending=1))
        self.assertEqual(self.audio.deleted, ["first", "second", "last"])
        self.assertEqual(self.repository.finish_calls[0][0], [CleanupOutcome(8, "OSError: cannot delete first")])

    def test_factory_is_lazy_cached_and_its_error_does_not_stop_other_categories(self):
        failing_audio = StorageFactory(error=RuntimeError("audio unavailable"))
        service = StorageCleanupService(
            self.repository,
            audio_storage=failing_audio,
            material_storage=self.material_factory,
            assignment_storage=self.assignment_factory,
            clock=lambda: 100,
        )
        self.repository.jobs = [
            ClaimedCleanupJob(1, CleanupKeys(audio=("one",), material=("material-one",)), 3700),
            ClaimedCleanupJob(2, CleanupKeys(audio=("two",), material=("material-two",)), 3700),
        ]
        self.repository.result = CleanupBatchResult(failed=2, pending=2)

        result = service.process_batch()

        self.assertEqual(result, CleanupSummary(failed=2, pending=2))
        self.assertEqual(failing_audio.calls, 1)
        self.assertEqual(self.material_factory.calls, 1)
        self.assertEqual(self.material.deleted, ["material-one", "material-two"])
        self.assertEqual(
            [outcome.error for outcome in self.repository.finish_calls[0][0]],
            ["RuntimeError: audio unavailable", "RuntimeError: audio unavailable"],
        )

    def test_decode_error_skips_storage_and_empty_batch_reports_pending(self):
        self.repository.jobs = [ClaimedCleanupJob(9, CleanupKeys(), 3700, "ValueError: invalid cleanup payload")]
        self.repository.result = CleanupBatchResult(failed=1, pending=2)

        self.assertEqual(self.service.process_batch(), CleanupSummary(failed=1, pending=2))
        self.assertEqual(
            self.repository.finish_calls[0][0],
            [CleanupOutcome(9, "ValueError: invalid cleanup payload")],
        )
        self.assertEqual(
            (self.audio_factory.calls, self.material_factory.calls, self.assignment_factory.calls), (0, 0, 0)
        )

        self.repository.jobs = []
        self.repository.pending = 3
        self.assertEqual(self.service.process_batch(now=200), CleanupSummary(pending=3))


if __name__ == "__main__":
    unittest.main()
