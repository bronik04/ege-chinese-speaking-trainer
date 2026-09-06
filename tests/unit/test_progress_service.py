import copy
import unittest

from trainer.services.progress import ProgressError, ProgressService
from trainer.services.progress_repository import ProgressDataError, ProgressRecord


def valid_v2():
    return {
        "version": 2,
        "updatedAt": "2026-09-06T10:15:30Z",
        "settings": {"lastVariant": "open-2026", "fastMode": False},
        "runs": [],
        "activeRun": None,
    }


class FakeProgressRepository:
    def __init__(self, record=None):
        self.record = record
        self.saved = []
        self.get_error = None
        self.save_error = None

    def get(self, user_id):
        if self.get_error is not None:
            raise self.get_error
        return self.record

    def save(self, user_id, document, updated_at):
        if self.save_error is not None:
            raise self.save_error
        self.saved.append((user_id, document, updated_at))


class ProgressServiceTest(unittest.TestCase):
    def test_get_migrates_v1_without_saving_or_mutating_repository_data(self):
        source = {"version": 1, "extra": "drop"}
        original = copy.deepcopy(source)
        repository = FakeProgressRepository(ProgressRecord(source, 1000))

        result = ProgressService(repository).get(7)

        self.assertEqual(result.updated_at, 1000)
        self.assertEqual(
            result.document,
            {
                "version": 2,
                "updatedAt": "1970-01-01T00:00:00.000Z",
                "settings": {"lastVariant": None, "fastMode": False},
                "runs": [],
                "activeRun": None,
            },
        )
        self.assertEqual(source, original)
        self.assertEqual(repository.saved, [])

    def test_get_returns_none_without_attempting_a_write(self):
        repository = FakeProgressRepository()
        self.assertIsNone(ProgressService(repository).get(7))
        self.assertEqual(repository.saved, [])

    def test_put_persists_only_a_fresh_canonical_v2_document(self):
        source = {"version": 1}
        repository = FakeProgressRepository()
        service = ProgressService(repository, clock=lambda: 1000.9)

        self.assertEqual(service.put(7, source), 1000)

        self.assertEqual(source, {"version": 1})
        self.assertEqual(repository.saved[0][0::2], (7, 1000))
        saved = repository.saved[0][1]
        self.assertEqual(saved["version"], 2)
        self.assertEqual(saved["runs"], [])
        self.assertIsNot(saved, source)

    def test_put_canonicalizes_valid_v2_timestamps(self):
        source = valid_v2()
        repository = FakeProgressRepository()
        ProgressService(repository, clock=lambda: 1000).put(7, source)
        self.assertEqual(repository.saved[0][1]["updatedAt"], "2026-09-06T10:15:30.000Z")

    def test_invalid_put_stops_before_clock_and_repository(self):
        repository = FakeProgressRepository()
        clock_calls = []
        service = ProgressService(repository, clock=lambda: clock_calls.append(True))
        for document, reason in (
            ({}, "invalid_document"),
            ({"version": 1, "runs": None}, "invalid_document"),
            ({"version": 1, "runs": [None] * 201}, "history_too_large"),
        ):
            with self.subTest(document=document), self.assertRaises(ProgressError) as raised:
                service.put(7, document)
            self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(clock_calls, [])
        self.assertEqual(repository.saved, [])

    def test_get_maps_stored_json_and_contract_failures_to_one_service_error(self):
        for failure in (ProgressDataError("bad json"), ProgressRecord({"version": 9}, 1000)):
            repository = FakeProgressRepository(failure if isinstance(failure, ProgressRecord) else None)
            if isinstance(failure, Exception):
                repository.get_error = failure
            with self.subTest(failure=failure), self.assertRaises(ProgressError) as raised:
                ProgressService(repository).get(7)
            self.assertEqual(raised.exception.reason, "stored_document_invalid")
            self.assertEqual(repository.saved, [])

    def test_repository_failures_are_not_reported_as_contract_errors_or_success(self):
        repository = FakeProgressRepository()
        repository.get_error = OSError("read down")
        with self.assertRaisesRegex(OSError, "read down"):
            ProgressService(repository).get(7)

        repository.get_error = None
        repository.save_error = OSError("write down")
        with self.assertRaisesRegex(OSError, "write down"):
            ProgressService(repository).put(7, {"version": 1})
        self.assertEqual(repository.saved, [])
