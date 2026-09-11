import unittest
from unittest.mock import Mock, patch

from trainer.api.controllers import recordings
from trainer.api.errors import ApiError
from trainer.api.results import FileResult
from trainer.services.recording_access import RecordingAccessError
from trainer.services.recording_access_repository import RecordingActor, StoredFile


class RecordingsControllerTest(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.user = {
            "id": 7,
            "role": "teacher",
            "email": " Owner@Example.Test ",
            "emailVerified": True,
        }
        self.actor = RecordingActor(7, "teacher", " Owner@Example.Test ", True)
        self.stored = StoredFile("private/file.webm", "audio/webm", 10)
        self.patcher = patch.object(
            recordings.runtime,
            "recording_access_service",
            return_value=self.service,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_public_functions_delegate_actor_and_preserve_file_result(self):
        cases = (
            (recordings.recording_get, self.service.legacy_recording, 3),
            (recordings.review_recording_get, self.service.review_recording, 4),
            (recordings.review_asset_get, self.service.review_asset, 5),
        )
        for function, service_method, resource_id in cases:
            with self.subTest(function=function.__name__):
                service_method.return_value = self.stored

                result = function(resource_id, self.user)

                self.assertEqual(
                    result,
                    FileResult("private/file.webm", "audio/webm", 10),
                )
                service_method.assert_called_once_with(resource_id, self.actor)

    def test_known_service_errors_keep_public_404_contracts(self):
        cases = (
            (
                recordings.recording_get,
                self.service.legacy_recording,
                "legacy_recording_not_found",
                "not_found",
                "Запись не найдена",
            ),
            (
                recordings.review_recording_get,
                self.service.review_recording,
                "review_recording_not_found",
                "recording_not_found",
                "Запись не найдена",
            ),
            (
                recordings.review_asset_get,
                self.service.review_asset,
                "review_asset_not_found",
                "asset_not_found",
                "Изображение не найдено",
            ),
        )
        for function, service_method, reason, code, message in cases:
            with self.subTest(reason=reason):
                service_method.side_effect = RecordingAccessError(reason)

                with self.assertRaises(ApiError) as raised:
                    function(9, self.user)

                self.assertEqual(
                    (raised.exception.status, raised.exception.code, raised.exception.message),
                    (404, code, message),
                )

    def test_unknown_service_error_is_not_hidden(self):
        error = RecordingAccessError("unexpected")
        self.service.review_recording.side_effect = error

        with self.assertRaises(RecordingAccessError) as raised:
            recordings.review_recording_get(4, self.user)

        self.assertIs(raised.exception, error)
