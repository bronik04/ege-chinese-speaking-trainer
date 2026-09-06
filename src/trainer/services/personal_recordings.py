from __future__ import annotations

import secrets
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from trainer.services.personal_recording_repository import (
    PersonalRecordingAccess,
    PersonalRecordingAudioError,
    PersonalRecordingConflictError,
    PersonalRecordingData,
    PersonalRecordingRecord,
    PersonalRecordingRepository,
    PersonalRecordingStorage,
)

_EXTENSIONS = {
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
}

UPLOAD_INTENT_GRACE_SECONDS = 60 * 60


class PersonalRecordingError(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def _public_record(record: PersonalRecordingRecord) -> dict:
    return {
        "id": record.id,
        "runId": record.run_id,
        "variantId": record.variant_id,
        "taskNumber": record.task_number,
        "questionNumber": record.question_number,
        "label": record.label,
        "createdAt": record.created_at,
        "expiresAt": record.expires_at,
    }


class PersonalRecordingService:
    def __init__(
        self,
        repository: PersonalRecordingRepository,
        storage: PersonalRecordingStorage,
        *,
        temporary_root: Path,
        max_audio_body: int,
        duration_validator: Callable[[Path, int], float],
        upload_intent_grace_seconds: int,
        clock: Callable[[], float] = time.time,
        storage_token: Callable[[], str] | None = None,
    ):
        self._repository = repository
        self._storage = storage
        self._temporary_root = temporary_root
        self._max_audio_body = max_audio_body
        self._duration_validator = duration_validator
        self._upload_intent_grace_seconds = upload_intent_grace_seconds
        self._clock = clock
        self._storage_token = storage_token or (lambda: secrets.token_urlsafe(18))

    def _now(self) -> int:
        return int(self._clock())

    def create(
        self,
        student_id: int,
        data: PersonalRecordingData,
        body: bytes,
        content_type: str,
    ) -> dict:
        if data.task_number in {2, 3} and data.question_number != 1:
            raise PersonalRecordingError(
                "invalid_position",
                "Для заданий 2 и 3 допустима только одна запись ответа",
            )
        mime_type = content_type.split(";", 1)[0].lower()
        extension = _EXTENSIONS.get(mime_type)
        if not extension:
            raise PersonalRecordingError("unsupported_audio", "Неподдерживаемый формат аудио")
        if not 0 < len(body) <= self._max_audio_body:
            raise PersonalRecordingError("audio_too_large", "Запись превышает 15 МБ")

        self._temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=self._temporary_root,
            prefix="personal-recording-",
            suffix=f".{extension}",
            delete=False,
        ) as file:
            file.write(body)
            temporary_path = Path(file.name)
        try:
            try:
                duration = self._duration_validator(temporary_path, data.task_number)
            except PersonalRecordingAudioError as error:
                raise PersonalRecordingError(
                    "invalid_audio",
                    "Некорректная или слишком длинная аудиозапись",
                ) from error

            now = self._now()
            storage_key = f"personal-recordings/{student_id}/{self._storage_token()}.{extension}"
            cleanup_job_id = self._repository.create_upload_intent(
                storage_key,
                now,
                now + self._upload_intent_grace_seconds,
            )
            self._storage.put(storage_key, temporary_path, mime_type)
            try:
                record = self._repository.finalize_recording(
                    student_id,
                    data,
                    storage_key,
                    mime_type,
                    len(body),
                    duration,
                    cleanup_job_id,
                    now,
                )
            except PersonalRecordingConflictError as error:
                raise PersonalRecordingError(
                    "recording_exists",
                    "Запись для этого задания уже сохранена",
                ) from error
            return _public_record(record)
        finally:
            temporary_path.unlink(missing_ok=True)

    def list(self, student_id: int) -> list[dict]:
        return [_public_record(record) for record in self._repository.recordings(student_id, self._now())]

    def file(self, recording_id: int, student_id: int) -> PersonalRecordingAccess:
        access = self._repository.recording_file(recording_id, student_id, self._now())
        if access is None:
            raise PersonalRecordingError("recording_not_found", "Запись не найдена")
        return access
