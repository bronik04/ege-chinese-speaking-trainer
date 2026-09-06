from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from trainer.services.storage_cleanup_repository import CleanupOutcome, StorageCleanupRepository

CLEANUP_RETRY_DELAY_SECONDS = 60 * 60


@dataclass(frozen=True)
class CleanupSummary:
    completed: int = 0
    failed: int = 0
    pending: int = 0


class CleanupStorage(Protocol):
    def delete(self, key: str) -> None: ...


StorageFactory = Callable[[], CleanupStorage]


class StorageCleanupService:
    def __init__(
        self,
        repository: StorageCleanupRepository,
        *,
        audio_storage: StorageFactory,
        material_storage: StorageFactory,
        assignment_storage: StorageFactory,
        clock: Callable[[], float] = time.time,
        lease_seconds: int = CLEANUP_RETRY_DELAY_SECONDS,
        retry_delay_seconds: int = CLEANUP_RETRY_DELAY_SECONDS,
    ):
        self._repository = repository
        self._audio_storage = audio_storage
        self._material_storage = material_storage
        self._assignment_storage = assignment_storage
        self._clock = clock
        self._lease_seconds = int(lease_seconds)
        self._retry_delay_seconds = int(retry_delay_seconds)

    def expire_batch(self, *, limit: int = 500, now: int | None = None) -> int:
        moment = int(self._clock()) if now is None else int(now)
        return self._repository.expire_recordings(now=moment, limit=max(0, int(limit)))

    def process_batch(self, *, limit: int = 50, now: int | None = None) -> CleanupSummary:
        moment = int(self._clock()) if now is None else int(now)
        lease_until = moment + self._lease_seconds
        jobs = self._repository.claim_jobs(
            now=moment,
            lease_until=lease_until,
            limit=max(0, int(limit)),
        )
        if not jobs:
            return CleanupSummary(pending=self._repository.pending_jobs())

        resolved: dict[StorageFactory, CleanupStorage | Exception] = {}

        def resolved_storage(factory: StorageFactory) -> CleanupStorage:
            if factory not in resolved:
                try:
                    resolved[factory] = factory()
                except Exception as error:
                    resolved[factory] = error
            value = resolved[factory]
            if isinstance(value, Exception):
                raise value
            return value

        outcomes: list[CleanupOutcome] = []
        for job in jobs:
            error_text = job.error
            if error_text is None:
                failures: list[Exception] = []
                for factory, keys in (
                    (self._audio_storage, job.keys.audio),
                    (self._material_storage, job.keys.material),
                    (self._assignment_storage, job.keys.assignment),
                ):
                    if not keys:
                        continue
                    try:
                        storage = resolved_storage(factory)
                    except Exception as error:
                        failures.append(error)
                        continue
                    for key in keys:
                        try:
                            storage.delete(key)
                        except FileNotFoundError:
                            continue
                        except Exception as error:
                            failures.append(error)
                if failures:
                    error = failures[0]
                    error_text = f"{type(error).__name__}: {error}"
            outcomes.append(CleanupOutcome(job.id, error_text))

        result = self._repository.finish_jobs(
            outcomes,
            lease_until=lease_until,
            now=moment,
            retry_at=moment + self._retry_delay_seconds,
        )
        return CleanupSummary(result.completed, result.failed, result.pending)
