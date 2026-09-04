import time
from collections.abc import Callable
from typing import Any

from trainer.domain.progress import ProgressValidationError, validate_progress
from trainer.services.progress_repository import ProgressRecord, ProgressRepository


class ProgressError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ProgressService:
    def __init__(self, repository: ProgressRepository, *, clock: Callable[[], float] = time.time):
        self._repository = repository
        self._clock = clock

    def get(self, user_id: int) -> ProgressRecord | None:
        return self._repository.get(user_id)

    def put(self, user_id: int, document: dict[str, Any]) -> int:
        try:
            validate_progress(document)
        except ProgressValidationError as error:
            raise ProgressError(error.reason) from error
        updated_at = int(self._clock())
        self._repository.save(user_id, document, updated_at)
        return updated_at
