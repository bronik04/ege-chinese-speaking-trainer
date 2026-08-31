from __future__ import annotations

import unittest
from http import HTTPStatus
from unittest.mock import Mock, patch

from trainer.api.controllers import personal_recordings
from trainer.api.errors import ApiError
from trainer.api.results import RequestContext
from trainer.api.schemas import PersonalRecordingUpload
from trainer.services.personal_recording_repository import PersonalRecordingAccess, PersonalRecordingData
from trainer.services.personal_recordings import PersonalRecordingError


class PersonalRecordingControllerTest(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.user = {"id": 17}
        self.payload = PersonalRecordingUpload(
            runId="run-1",
            variantId="demo-2026",
            taskNumber=2,
            questionNumber=1,
            label="Answer",
        )
        self.context = RequestContext("127.0.0.1", "test")
        self.patcher = patch.object(
            personal_recordings.runtime,
            "personal_recording_service",
            return_value=self.service,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_create_maps_schema_and_delegates_to_service(self):
        self.service.create.return_value = {"id": 9}

        result = personal_recordings.personal_recording_create(
            self.payload,
            b"audio",
            "audio/webm; codecs=opus",
            self.user,
            self.context,
        )

        self.assertEqual(result.status, HTTPStatus.CREATED)
        self.assertEqual(result.payload, {"recording": {"id": 9}})
        self.service.create.assert_called_once_with(
            17,
            PersonalRecordingData("run-1", "demo-2026", 2, 1, "Answer"),
            b"audio",
            "audio/webm; codecs=opus",
        )

    def test_list_and_file_delegate_and_preserve_transport_results(self):
        self.service.list.return_value = [{"id": 9}]
        self.service.file.return_value = PersonalRecordingAccess("private/9.webm", "audio/webm", 42)

        listed = personal_recordings.personal_recordings_list(self.user)
        stored = personal_recordings.personal_recording_get(9, self.user)

        self.assertEqual(listed.payload, {"recordings": [{"id": 9}]})
        self.assertEqual((stored.key, stored.mime_type, stored.size_bytes), ("private/9.webm", "audio/webm", 42))
        self.service.list.assert_called_once_with(17)
        self.service.file.assert_called_once_with(9, 17)

    def test_service_errors_keep_existing_http_contract(self):
        cases = (
            ("invalid_position", HTTPStatus.BAD_REQUEST, "invalid_request"),
            ("unsupported_audio", HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type"),
            ("audio_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large"),
            ("invalid_audio", HTTPStatus.UNPROCESSABLE_ENTITY, "validation_failed"),
            ("recording_exists", HTTPStatus.CONFLICT, "personal_recording_exists"),
            ("recording_not_found", HTTPStatus.NOT_FOUND, "recording_not_found"),
        )
        for reason, status, code in cases:
            with self.subTest(reason=reason):
                error = personal_recordings._service_error(PersonalRecordingError(reason, "message"))
                self.assertIsInstance(error, ApiError)
                self.assertEqual((error.status, error.code, error.message), (status, code, "message"))

    def test_unknown_service_error_is_not_hidden_as_a_transport_error(self):
        error = PersonalRecordingError("unexpected", "bug")

        with self.assertRaises(PersonalRecordingError) as raised:
            personal_recordings._service_error(error)

        self.assertIs(raised.exception, error)


if __name__ == "__main__":
    unittest.main()
