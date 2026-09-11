import time
from collections.abc import Callable

from trainer.domain.progress import ProgressValidationError, normalize_progress, progress_to_dict
from trainer.services.progress_repository import ProgressDataError, ProgressRecord, ProgressRepository


class ProgressError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ProgressService:
    def __init__(self, repository: ProgressRepository, *, clock: Callable[[], float] = time.time):
        self._repository = repository
        self._clock = clock

    def get(self, user_id: int) -> ProgressRecord | None:
        try:
            record = self._repository.get(user_id)
        except ProgressDataError as error:
            raise ProgressError("stored_document_invalid") from error
        if record is None:
            return None
        try:
            document = progress_to_dict(normalize_progress(record.document))
        except ProgressValidationError as error:
            raise ProgressError("stored_document_invalid") from error
        return ProgressRecord(document, record.updated_at)

    def put(self, user_id: int, document: dict[str, object]) -> int:
        try:
            canonical = progress_to_dict(normalize_progress(document))
        except ProgressValidationError as error:
            raise ProgressError(error.reason) from error
        updated_at = int(self._clock())
        self._repository.save(user_id, canonical, updated_at)
        return updated_at
