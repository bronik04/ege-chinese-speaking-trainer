from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CleanupKeys:
    audio: tuple[str, ...] = ()
    material: tuple[str, ...] = ()
    assignment: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimedCleanupJob:
    id: int
    keys: CleanupKeys
    lease_until: int
    error: str | None = None


@dataclass(frozen=True)
class CleanupOutcome:
    job_id: int
    error: str | None = None


@dataclass(frozen=True)
class CleanupBatchResult:
    completed: int = 0
    failed: int = 0
    pending: int = 0


class StorageCleanupRepository(Protocol):
    def expire_recordings(self, *, now: int, limit: int) -> int: ...

    def claim_jobs(self, *, now: int, lease_until: int, limit: int) -> list[ClaimedCleanupJob]: ...

    def finish_jobs(
        self,
        outcomes: Sequence[CleanupOutcome],
        *,
        lease_until: int,
        now: int,
        retry_at: int,
    ) -> CleanupBatchResult: ...

    def pending_jobs(self) -> int: ...
