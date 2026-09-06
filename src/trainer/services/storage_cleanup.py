from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trainer.infrastructure.database.core import begin_immediate
from trainer.infrastructure.storage import storage_from_env
from trainer.services.storage_cleanup_repository import CleanupOutcome, StorageCleanupRepository

UPLOAD_INTENT_GRACE_SECONDS = 60 * 60
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


def _keys(values) -> list[str]:
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def account_review_storage_keys(database, student_id: int) -> tuple[list[str], list[str]]:
    recordings = database.execute(
        """SELECT review_request_recordings.storage_key
           FROM review_request_recordings
           JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
           JOIN review_requests ON review_requests.id=review_request_items.request_id
           WHERE review_requests.student_id=?""",
        (student_id,),
    ).fetchall()
    assets = database.execute(
        """SELECT review_request_assets.storage_key
           FROM review_request_assets
           JOIN review_requests ON review_requests.id=review_request_assets.request_id
           WHERE review_requests.student_id=?""",
        (student_id,),
    ).fetchall()
    personal_recordings = database.execute(
        "SELECT storage_key FROM personal_recordings WHERE student_id=?", (student_id,)
    ).fetchall()
    return (
        _keys(row["storage_key"] for row in [*recordings, *personal_recordings]),
        _keys(row["storage_key"] for row in assets),
    )


def expire_recordings(database, *, now: int | None = None, limit: int = 500) -> int:
    """Remove expired audio metadata and durably queue its private blobs for deletion."""
    moment = int(time.time()) if now is None else int(now)
    maximum = max(0, int(limit))
    begin_immediate(database)
    try:
        rows = database.execute(
            """SELECT source,id,storage_key FROM (
                   SELECT 'personal' AS source,id,storage_key,expires_at FROM personal_recordings
                   WHERE expires_at<=?
                   UNION ALL
                   SELECT 'review' AS source,id,storage_key,expires_at FROM review_request_recordings
                   WHERE expires_at<=?
               ) ORDER BY expires_at,id,source LIMIT ?""",
            (moment, moment, maximum),
        ).fetchall()
        archive_rows = [row for row in rows if row["source"] == "personal"]
        review_rows = [row for row in rows if row["source"] == "review"]
        database.executemany("DELETE FROM personal_recordings WHERE id=?", [(row["id"],) for row in archive_rows])
        database.executemany("DELETE FROM review_request_recordings WHERE id=?", [(row["id"],) for row in review_rows])
        keys = _keys(row["storage_key"] for row in [*archive_rows, *review_rows])
        if keys:
            enqueue_cleanup_job(database, audio_keys=keys, material_keys=[], assignment_keys=[], now=moment)
        database.commit()
    except Exception:
        database.rollback()
        raise
    return len(archive_rows) + len(review_rows)


def enqueue_cleanup_job(
    database,
    *,
    audio_keys,
    material_keys,
    assignment_keys,
    now: int | None = None,
    available_at: int | None = None,
) -> int:
    moment = int(time.time()) if now is None else int(now)
    available = moment if available_at is None else int(available_at)
    cursor = database.execute(
        """
        INSERT INTO storage_cleanup_jobs(
            audio_keys_json, material_keys_json, assignment_keys_json, attempts, created_at, updated_at, available_at
        ) VALUES (?, ?, ?, 0, ?, ?, ?)
        """,
        (
            json.dumps(_keys(audio_keys)),
            json.dumps(_keys(material_keys)),
            json.dumps(_keys(assignment_keys)),
            moment,
            moment,
            available,
        ),
    )
    return cursor.lastrowid


def _delete_keys(root: Path, keys: list[str]) -> Exception | None:
    if not keys:
        return None
    try:
        storage = storage_from_env(root)
    except Exception as error:
        return error
    failure: Exception | None = None
    for key in keys:
        try:
            storage.delete(key)
        except FileNotFoundError:
            continue
        except Exception as error:
            failure = failure or error
    return failure


def process_cleanup_jobs(
    database,
    *,
    audio_root: Path,
    material_root: Path,
    assignment_root: Path,
    limit: int = 50,
    now: int | None = None,
) -> CleanupSummary:
    moment = int(time.time()) if now is None else int(now)
    jobs = database.execute(
        """
        SELECT id, audio_keys_json, material_keys_json, assignment_keys_json
        FROM storage_cleanup_jobs
        WHERE available_at <= ?
        ORDER BY available_at, id LIMIT ?
        """,
        (moment, limit),
    ).fetchall()
    completed = 0
    failed = 0
    for job in jobs:
        try:
            failures = [
                error
                for root, field in (
                    (audio_root, "audio_keys_json"),
                    (material_root, "material_keys_json"),
                    (assignment_root, "assignment_keys_json"),
                )
                if (error := _delete_keys(root, _keys(json.loads(job[field]))))
            ]
        except (TypeError, ValueError) as error:
            failures = [error]
        if failures:
            error = failures[0]
            database.execute(
                """
                UPDATE storage_cleanup_jobs
                SET attempts = attempts + 1, last_error = ?, updated_at = ?, available_at = ?
                WHERE id = ?
                """,
                (
                    f"{type(error).__name__}: {error}",
                    moment,
                    moment + CLEANUP_RETRY_DELAY_SECONDS,
                    job["id"],
                ),
            )
            failed += 1
        else:
            database.execute("DELETE FROM storage_cleanup_jobs WHERE id = ?", (job["id"],))
            completed += 1
    pending = database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0]
    return CleanupSummary(completed=completed, failed=failed, pending=pending)
