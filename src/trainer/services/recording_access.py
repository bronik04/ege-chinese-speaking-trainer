import time
from collections.abc import Callable
from typing import Protocol

from trainer.services.recording_access_repository import (
    RecordingAccessRepository,
    RecordingActor,
    StoredFile,
)


class RecordingAccessError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _ReviewVisibilityRecord(Protocol):
    status: str
    student_id: int


class RecordingAccessService:
    def __init__(
        self,
        repository: RecordingAccessRepository,
        *,
        owner_email: str,
        clock: Callable[[], float] = time.time,
    ):
        self._repository = repository
        self._owner_email = owner_email.strip().lower()
        self._clock = clock

    def _owner_allowed(self, record: _ReviewVisibilityRecord, actor: RecordingActor) -> bool:
        return bool(
            self._owner_email
            and record.status in {"queued", "reviewed"}
            and actor.role == "teacher"
            and actor.email_verified
            and actor.email.strip().lower() == self._owner_email
        )

    def legacy_recording(self, recording_id: int, actor: RecordingActor) -> StoredFile:
        record = self._repository.legacy_recording(recording_id)
        if (
            record is None
            or actor.id not in {record.student_id, record.teacher_id}
            or (record.status == "uploading" and actor.id != record.student_id)
        ):
            raise RecordingAccessError("legacy_recording_not_found")
        return record.file

    def review_recording(self, recording_id: int, actor: RecordingActor) -> StoredFile:
        record = self._repository.review_recording(recording_id)
        if record is None or record.expires_at <= int(self._clock()):
            raise RecordingAccessError("review_recording_not_found")
        if actor.id != record.student_id and not self._owner_allowed(record, actor):
            raise RecordingAccessError("review_recording_not_found")
        return record.file

    def review_asset(self, asset_id: int, actor: RecordingActor) -> StoredFile:
        record = self._repository.review_asset(asset_id)
        if record is None or (actor.id != record.student_id and not self._owner_allowed(record, actor)):
            raise RecordingAccessError("review_asset_not_found")
        return record.file
