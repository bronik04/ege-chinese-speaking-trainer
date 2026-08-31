from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PersonalRecordingData:
    run_id: str
    variant_id: str
    task_number: int
    question_number: int
    label: str


@dataclass(frozen=True)
class PersonalRecordingRecord:
    id: int
    run_id: str
    variant_id: str
    task_number: int
    question_number: int
    label: str
    created_at: int
    expires_at: int


@dataclass(frozen=True)
class PersonalRecordingAccess:
    storage_key: str
    mime_type: str
    size_bytes: int


class PersonalRecordingConflictError(Exception):
    pass


class PersonalRecordingAudioError(Exception):
    pass


class PersonalRecordingIntentError(Exception):
    pass


class PersonalRecordingStorage(Protocol):
    def put(self, key: str, source: Path, content_type: str) -> None: ...


class PersonalRecordingRepository(Protocol):
    def create_upload_intent(self, storage_key: str, now: int, available_at: int) -> int: ...

    def finalize_recording(
        self,
        student_id: int,
        data: PersonalRecordingData,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        duration_seconds: float,
        cleanup_job_id: int,
        now: int,
    ) -> PersonalRecordingRecord: ...

    def recordings(self, student_id: int, now: int) -> list[PersonalRecordingRecord]: ...

    def recording_file(
        self,
        recording_id: int,
        student_id: int,
        now: int,
    ) -> PersonalRecordingAccess | None: ...
