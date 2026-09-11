from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing

from trainer.infrastructure.database.core import begin_immediate
from trainer.services.storage_cleanup_repository import (
    ClaimedCleanupJob,
    CleanupBatchResult,
    CleanupKeys,
    CleanupOutcome,
)


def _keys(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def _decode(value: str) -> tuple[str, ...]:
    decoded = json.loads(value)
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise ValueError("invalid cleanup payload")
    return _keys(decoded)


class SQLiteStorageCleanupQueue:
    def __init__(self, database: sqlite3.Connection):
        self.database = database

    def enqueue(
        self,
        keys: CleanupKeys,
        *,
        now: int,
        available_at: int | None = None,
    ) -> int:
        moment = int(now)
        available = moment if available_at is None else int(available_at)
        cursor = self.database.execute(
            """INSERT INTO storage_cleanup_jobs(
                   audio_keys_json,material_keys_json,assignment_keys_json,
                   attempts,created_at,updated_at,available_at)
               VALUES (?,?,?,0,?,?,?)""",
            (
                json.dumps(_keys(keys.audio)),
                json.dumps(_keys(keys.material)),
                json.dumps(_keys(keys.assignment)),
                moment,
                moment,
                available,
            ),
        )
        return int(cursor.lastrowid)

    def cancel(self, job_id: int) -> bool:
        cursor = self.database.execute("DELETE FROM storage_cleanup_jobs WHERE id=?", (job_id,))
        return cursor.rowcount == 1


class SQLiteStorageCleanupRepository:
    def __init__(self, connect_factory: Callable[[], sqlite3.Connection]):
        self._connect = connect_factory

    def expire_recordings(self, *, now: int, limit: int) -> int:
        moment = int(now)
        maximum = max(0, int(limit))
        with closing(self._connect()) as database:
            begin_immediate(database)
            try:
                rows = database.execute(
                    """SELECT source,id,storage_key FROM (
                           SELECT 'personal' AS source,id,storage_key,expires_at
                           FROM personal_recordings WHERE expires_at<=?
                           UNION ALL
                           SELECT 'review' AS source,id,storage_key,expires_at
                           FROM review_request_recordings WHERE expires_at<=?
                       ) ORDER BY expires_at,id,source LIMIT ?""",
                    (moment, moment, maximum),
                ).fetchall()
                personal_rows = [row for row in rows if row["source"] == "personal"]
                review_rows = [row for row in rows if row["source"] == "review"]
                database.executemany(
                    "DELETE FROM personal_recordings WHERE id=?",
                    [(row["id"],) for row in personal_rows],
                )
                database.executemany(
                    "DELETE FROM review_request_recordings WHERE id=?",
                    [(row["id"],) for row in review_rows],
                )
                audio_keys = _keys(row["storage_key"] for row in [*personal_rows, *review_rows])
                if audio_keys:
                    SQLiteStorageCleanupQueue(database).enqueue(
                        CleanupKeys(audio=audio_keys),
                        now=moment,
                    )
                database.commit()
            except Exception:
                database.rollback()
                raise
        return len(rows)

    def claim_jobs(self, *, now: int, lease_until: int, limit: int) -> list[ClaimedCleanupJob]:
        moment = int(now)
        claimed_until = int(lease_until)
        maximum = max(0, int(limit))
        with closing(self._connect()) as database:
            begin_immediate(database)
            try:
                rows = database.execute(
                    """SELECT id,audio_keys_json,material_keys_json,assignment_keys_json
                       FROM storage_cleanup_jobs
                       WHERE available_at<=?
                       ORDER BY available_at,id LIMIT ?""",
                    (moment, maximum),
                ).fetchall()
                database.executemany(
                    """UPDATE storage_cleanup_jobs SET available_at=?,updated_at=?
                       WHERE id=? AND available_at<=?""",
                    [(claimed_until, moment, row["id"], moment) for row in rows],
                )
                database.commit()
            except Exception:
                database.rollback()
                raise

        jobs: list[ClaimedCleanupJob] = []
        for row in rows:
            try:
                keys = CleanupKeys(
                    _decode(row["audio_keys_json"]),
                    _decode(row["material_keys_json"]),
                    _decode(row["assignment_keys_json"]),
                )
                error = None
            except (TypeError, ValueError) as decode_error:
                keys = CleanupKeys()
                error = f"{type(decode_error).__name__}: {decode_error}"
            jobs.append(ClaimedCleanupJob(row["id"], keys, claimed_until, error))
        return jobs

    def finish_jobs(
        self,
        outcomes: Sequence[CleanupOutcome],
        *,
        lease_until: int,
        now: int,
        retry_at: int,
    ) -> CleanupBatchResult:
        completed = 0
        failed = 0
        with closing(self._connect()) as database:
            begin_immediate(database)
            try:
                for outcome in outcomes:
                    if outcome.error is None:
                        cursor = database.execute(
                            "DELETE FROM storage_cleanup_jobs WHERE id=? AND available_at=?",
                            (outcome.job_id, lease_until),
                        )
                        completed += int(cursor.rowcount == 1)
                    else:
                        cursor = database.execute(
                            """UPDATE storage_cleanup_jobs
                               SET attempts=attempts+1,last_error=?,updated_at=?,available_at=?
                               WHERE id=? AND available_at=?""",
                            (outcome.error, now, retry_at, outcome.job_id, lease_until),
                        )
                        failed += int(cursor.rowcount == 1)
                pending = database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0]
                database.commit()
            except Exception:
                database.rollback()
                raise
        return CleanupBatchResult(completed, failed, pending)

    def pending_jobs(self) -> int:
        with closing(self._connect()) as database:
            return int(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0])
