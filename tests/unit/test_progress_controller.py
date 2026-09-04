import unittest
from unittest.mock import Mock, patch

from trainer.api import runtime
from trainer.api.controllers import progress
from trainer.api.errors import ApiError
from trainer.api.schemas import ProgressRequest
from trainer.services.progress import ProgressError
from trainer.services.progress_repository import ProgressRecord


class ProgressControllerTest(unittest.TestCase):
    def test_transport_results_and_delegation(self):
        service = Mock()
        payload = ProgressRequest(progress={"version": 1})
        with patch.object(runtime, "progress_service", return_value=service):
            service.get.return_value = None
            self.assertEqual(progress.progress_get({"id": 7}).payload, {"progress": None, "updatedAt": None})
            service.get.return_value = ProgressRecord(payload.progress, 1000)
            self.assertEqual(
                progress.progress_get({"id": 7}).payload, {"progress": payload.progress, "updatedAt": 1000}
            )
            service.get.assert_called_with(7)
            service.put.return_value = 1001
            result = progress.progress_put(payload, {"id": 7})
            self.assertEqual((result.status, result.payload), (200, {"ok": True, "updatedAt": 1001}))
            service.put.assert_called_once_with(7, payload.progress)

    def test_semantic_errors_keep_http_contract(self):
        service = Mock()
        with patch.object(runtime, "progress_service", return_value=service):
            for reason, message in (
                ("invalid_document", "Invalid progress document"),
                ("history_too_large", "Progress history is too large"),
            ):
                service.put.side_effect = ProgressError(reason)
                with self.assertRaises(ApiError) as raised:
                    progress.progress_put(ProgressRequest(progress={}), {"id": 7})
                self.assertEqual(
                    (raised.exception.status, raised.exception.code, raised.exception.message),
                    (400, "invalid_request", message),
                )
            unexpected = ProgressError("unexpected")
            service.put.side_effect = unexpected
            with self.assertRaises(ProgressError) as raised:
                progress.progress_put(ProgressRequest(progress={}), {"id": 7})
            self.assertIs(raised.exception, unexpected)
