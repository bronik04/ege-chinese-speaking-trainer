import unittest
from unittest.mock import Mock

from trainer.domain.progress import ProgressValidationError, validate_progress
from trainer.services.progress import ProgressError, ProgressService
from trainer.services.progress_repository import ProgressRecord


class ProgressServiceTest(unittest.TestCase):
    def test_domain_accepts_existing_shapes_without_mutation(self):
        for version in (1, True, 1.0):
            for document in ({"version": version}, {"version": version, "runs": [None] * 200, "extra": "中文"}):
                with self.subTest(document=document):
                    original = document.copy()
                    validate_progress(document)
                    self.assertEqual(document, original)

    def test_domain_rejects_invalid_documents(self):
        cases = (
            (None, "invalid_document"),
            ([], "invalid_document"),
            ({}, "invalid_document"),
            ({"version": "1"}, "invalid_document"),
            ({"version": 2}, "invalid_document"),
            ({"version": 1, "runs": None}, "history_too_large"),
            ({"version": 1, "runs": {}}, "history_too_large"),
            ({"version": 1, "runs": [None] * 201}, "history_too_large"),
        )
        for document, reason in cases:
            with self.subTest(document=document):
                with self.assertRaises(ProgressValidationError) as raised:
                    validate_progress(document)
                self.assertEqual(raised.exception.reason, reason)

    def test_service_validates_before_clock_or_repository(self):
        repository, clock = Mock(), Mock()
        service = ProgressService(repository, clock=clock)
        for document, reason in (({}, "invalid_document"), ({"version": 1, "runs": None}, "history_too_large")):
            with self.assertRaises(ProgressError) as raised:
                service.put(7, document)
            self.assertEqual(raised.exception.reason, reason)
        repository.save.assert_not_called()
        clock.assert_not_called()

    def test_put_preserves_document_and_returns_integer_server_time(self):
        repository = Mock()
        document = {"version": 1, "updatedAt": "client", "runs": [], "extra": "中文"}
        service = ProgressService(repository, clock=lambda: 1000.9)
        self.assertEqual(service.put(7, document), 1000)
        repository.save.assert_called_once_with(7, document, 1000)

    def test_get_returns_repository_record_or_none(self):
        repository = Mock()
        service = ProgressService(repository)
        for record in (None, ProgressRecord({"version": 1}, 1000), ProgressRecord([], 1001)):
            repository.get.return_value = record
            self.assertIs(service.get(7), record)
            repository.get.assert_called_with(7)

    def test_repository_failures_are_not_reported_as_success(self):
        repository = Mock()
        repository.save.side_effect = OSError("storage down")
        repository.get.side_effect = OSError("storage down")
        service = ProgressService(repository)
        with self.assertRaisesRegex(OSError, "storage down"):
            service.put(7, {"version": 1})
        with self.assertRaisesRegex(OSError, "storage down"):
            service.get(7)
