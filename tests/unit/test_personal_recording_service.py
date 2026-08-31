from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trainer.services.personal_recording_repository import (
    PersonalRecordingAccess,
    PersonalRecordingAudioError,
    PersonalRecordingConflictError,
    PersonalRecordingData,
    PersonalRecordingRecord,
)
from trainer.services.personal_recordings import PersonalRecordingError, PersonalRecordingService


class FakePersonalRecordingRepository:
    def __init__(self):
        self.operations: list[str] = []
        self.intents: dict[int, tuple[str, int, int]] = {}
        self.records: list[PersonalRecordingRecord] = []
        self.access: PersonalRecordingAccess | None = None
        self.conflict = False

    def create_upload_intent(self, storage_key, now, available_at):
        self.operations.append("intent")
        intent_id = len(self.intents) + 1
        self.intents[intent_id] = (storage_key, now, available_at)
        return intent_id

    def finalize_recording(
        self,
        student_id,
        data,
        storage_key,
        mime_type,
        size_bytes,
        duration_seconds,
        cleanup_job_id,
        now,
    ):
        self.operations.append("finalize")
        if self.conflict:
            raise PersonalRecordingConflictError
        record = PersonalRecordingRecord(
            id=11,
            run_id=data.run_id,
            variant_id=data.variant_id,
            task_number=data.task_number,
            question_number=data.question_number,
            label=data.label,
            created_at=now,
            expires_at=now + 30,
        )
        self.records.append(record)
        self.intents.pop(cleanup_job_id)
        return record

    def recordings(self, student_id, now):
        self.operations.append(f"list:{student_id}:{now}")
        return list(self.records)

    def recording_file(self, recording_id, student_id, now):
        self.operations.append(f"file:{recording_id}:{student_id}:{now}")
        return self.access


class FakeStorage:
    def __init__(self, repository: FakePersonalRecordingRepository):
        self.repository = repository
        self.puts: list[tuple[str, bytes, str]] = []
        self.error: Exception | None = None

    def put(self, key, source, content_type):
        self.repository.operations.append("put")
        if not self.repository.intents:
            raise AssertionError("storage put happened before durable intent")
        self.puts.append((key, source.read_bytes(), content_type))
        if self.error:
            raise self.error


class FakeDurationValidator:
    def __init__(self):
        self.calls: list[tuple[Path, int, bytes]] = []
        self.error: Exception | None = None

    def __call__(self, path, task_number):
        self.calls.append((path, task_number, path.read_bytes()))
        if self.error:
            raise self.error
        return 12.5


class PersonalRecordingServiceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.temporary_root = Path(self.directory.name)
        self.repository = FakePersonalRecordingRepository()
        self.storage = FakeStorage(self.repository)
        self.validator = FakeDurationValidator()
        self.service = PersonalRecordingService(
            self.repository,
            self.storage,
            temporary_root=self.temporary_root,
            max_audio_body=12,
            duration_validator=self.validator,
            upload_intent_grace_seconds=60,
            clock=lambda: 1000,
            storage_token=lambda: "private-token",
        )
        self.data = PersonalRecordingData("run-1", "demo-2026", 2, 1, "Answer")

    def tearDown(self):
        self.directory.cleanup()

    def temporary_files(self):
        return list(self.temporary_root.glob("personal-recording-*"))

    def test_create_commits_intent_before_storage_then_finalizes_and_cleans_temporary_file(self):
        recording = self.service.create(7, self.data, b"audio", "audio/webm; codecs=opus")

        self.assertEqual(self.repository.operations, ["intent", "put", "finalize"])
        self.assertEqual(self.repository.intents, {})
        self.assertEqual(
            self.storage.puts,
            [("personal-recordings/7/private-token.webm", b"audio", "audio/webm")],
        )
        self.assertEqual(self.validator.calls[0][1:], (2, b"audio"))
        self.assertEqual(
            recording,
            {
                "id": 11,
                "runId": "run-1",
                "variantId": "demo-2026",
                "taskNumber": 2,
                "questionNumber": 1,
                "label": "Answer",
                "createdAt": 1000,
                "expiresAt": 1030,
            },
        )
        self.assertEqual(self.temporary_files(), [])

    def test_validation_errors_have_no_database_storage_or_file_side_effects(self):
        cases = (
            (PersonalRecordingData("run", "demo", 2, 2, "Answer"), b"audio", "audio/webm", "invalid_position"),
            (self.data, b"audio", "audio/mpeg", "unsupported_audio"),
            (self.data, b"", "audio/webm", "audio_too_large"),
            (self.data, b"x" * 13, "audio/webm", "audio_too_large"),
        )
        for data, body, content_type, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaises(PersonalRecordingError) as raised:
                    self.service.create(7, data, body, content_type)
                self.assertEqual(raised.exception.reason, reason)
                self.assertEqual(self.repository.operations, [])
                self.assertEqual(self.storage.puts, [])
                self.assertEqual(self.temporary_files(), [])

    def test_invalid_audio_removes_temporary_file_before_any_external_write(self):
        self.validator.error = PersonalRecordingAudioError("invalid audio")

        with self.assertRaises(PersonalRecordingError) as raised:
            self.service.create(7, self.data, b"audio", "audio/webm")

        self.assertEqual(raised.exception.reason, "invalid_audio")
        self.assertEqual(self.repository.operations, [])
        self.assertEqual(self.temporary_files(), [])

    def test_storage_failure_keeps_intent_and_removes_temporary_file(self):
        self.storage.error = OSError("storage down")

        with self.assertRaisesRegex(OSError, "storage down"):
            self.service.create(7, self.data, b"audio", "audio/ogg")

        self.assertEqual(self.repository.operations, ["intent", "put"])
        intent = next(iter(self.repository.intents.values()))
        self.assertEqual(intent, ("personal-recordings/7/private-token.ogg", 1000, 1060))
        self.assertEqual(self.temporary_files(), [])

    def test_metadata_conflict_keeps_intent_and_uses_stable_semantic_error(self):
        self.repository.conflict = True

        with self.assertRaises(PersonalRecordingError) as raised:
            self.service.create(7, self.data, b"audio", "audio/mp4")

        self.assertEqual(raised.exception.reason, "recording_exists")
        self.assertEqual(self.repository.operations, ["intent", "put", "finalize"])
        self.assertEqual(len(self.repository.intents), 1)
        self.assertEqual(self.temporary_files(), [])

    def test_list_and_file_preserve_public_contract(self):
        self.repository.records = [
            PersonalRecordingRecord(3, "run", "demo", 1, 4, "Question", 900, 1200),
        ]
        self.repository.access = PersonalRecordingAccess("private.webm", "audio/webm", 42)

        self.assertEqual(
            self.service.list(7),
            [
                {
                    "id": 3,
                    "runId": "run",
                    "variantId": "demo",
                    "taskNumber": 1,
                    "questionNumber": 4,
                    "label": "Question",
                    "createdAt": 900,
                    "expiresAt": 1200,
                }
            ],
        )
        self.assertEqual(self.service.file(3, 7), self.repository.access)
        self.repository.access = None
        with self.assertRaises(PersonalRecordingError) as raised:
            self.service.file(3, 8)
        self.assertEqual(raised.exception.reason, "recording_not_found")


if __name__ == "__main__":
    unittest.main()
