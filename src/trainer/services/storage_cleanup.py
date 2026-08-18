from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from trainer.infrastructure.storage import storage_from_env


@dataclass(frozen=True)
class CleanupSummary:
    completed: int = 0
    failed: int = 0
    pending: int = 0


def _keys(values) -> list[str]:
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def enqueue_cleanup_job(
    database,
    *,
    audio_keys,
    material_keys,
    assignment_keys,
    now: int | None = None,
) -> int:
    moment = int(time.time()) if now is None else int(now)
    cursor = database.execute(
        """
        INSERT INTO storage_cleanup_jobs(
            audio_keys_json, material_keys_json, assignment_keys_json, attempts, created_at, updated_at
        ) VALUES (?, ?, ?, 0, ?, ?)
        """,
        (
            json.dumps(_keys(audio_keys)),
            json.dumps(_keys(material_keys)),
            json.dumps(_keys(assignment_keys)),
            moment,
            moment,
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
        FROM storage_cleanup_jobs ORDER BY created_at, id LIMIT ?
        """,
        (limit,),
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
                SET attempts = attempts + 1, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (f"{type(error).__name__}: {error}", moment, job["id"]),
            )
            failed += 1
        else:
            database.execute("DELETE FROM storage_cleanup_jobs WHERE id = ?", (job["id"],))
            completed += 1
    pending = database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0]
    return CleanupSummary(completed=completed, failed=failed, pending=pending)
