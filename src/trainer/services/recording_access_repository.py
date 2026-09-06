from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RecordingActor:
    id: int
    role: str
    email: str
    email_verified: bool


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class LegacyRecordingRecord:
    file: StoredFile
    status: str
    student_id: int
    teacher_id: int


@dataclass(frozen=True)
class ReviewRecordingRecord:
    file: StoredFile
    status: str
    student_id: int
    expires_at: int


@dataclass(frozen=True)
class ReviewAssetRecord:
    file: StoredFile
    status: str
    student_id: int


class RecordingAccessRepository(Protocol):
    def legacy_recording(self, recording_id: int) -> LegacyRecordingRecord | None: ...

    def review_recording(self, recording_id: int) -> ReviewRecordingRecord | None: ...

    def review_asset(self, asset_id: int) -> ReviewAssetRecord | None: ...
