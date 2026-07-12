from __future__ import annotations

import os
import time


def enabled() -> bool:
    return os.environ.get("TRAINER_TRANSCRIPTION_ENABLED", "0").lower() in {"1", "true", "yes"}


def enqueue(database, recording_id: int, now: int | None = None) -> None:
    timestamp = now or int(time.time())
    database.execute(
        """
        INSERT INTO transcription_jobs(recording_id, status, available_at, created_at, updated_at)
        VALUES (?, 'pending', ?, ?, ?)
        """,
        (recording_id, timestamp, timestamp, timestamp),
    )


def claim(database, now: int | None = None):
    timestamp = now or int(time.time())
    stale_before = timestamp - 15 * 60
    database.execute(
        """UPDATE recordings SET transcript_status = 'pending'
           WHERE id IN (SELECT recording_id FROM transcription_jobs
                        WHERE status = 'processing' AND locked_at < ?)""",
        (stale_before,),
    )
    database.execute(
        """UPDATE transcription_jobs SET status = 'pending', locked_at = NULL, available_at = ?, updated_at = ?
           WHERE status = 'processing' AND locked_at < ?""",
        (timestamp, timestamp, stale_before),
    )
    job = database.execute(
        """
        SELECT transcription_jobs.id, transcription_jobs.recording_id, transcription_jobs.attempts,
               recordings.file_name, recordings.mime_type
        FROM transcription_jobs JOIN recordings ON recordings.id = transcription_jobs.recording_id
        WHERE transcription_jobs.status = 'pending' AND transcription_jobs.available_at <= ?
        ORDER BY transcription_jobs.id LIMIT 1
        """,
        (timestamp,),
    ).fetchone()
    if not job:
        return None
    changed = database.execute(
        """
        UPDATE transcription_jobs SET status = 'processing', locked_at = ?, attempts = attempts + 1, updated_at = ?
        WHERE id = ? AND status = 'pending'
        """,
        (timestamp, timestamp, job["id"]),
    ).rowcount
    if changed:
        database.execute(
            "UPDATE recordings SET transcript_status = 'processing', transcript_error = NULL WHERE id = ?",
            (job["recording_id"],),
        )
    return dict(job) if changed else None


def complete(database, job: dict, text: str, now: int | None = None) -> None:
    timestamp = now or int(time.time())
    lease_attempt = int(job["attempts"]) + 1
    changed = database.execute(
        "UPDATE transcription_jobs SET status = 'completed', last_error = NULL, updated_at = ? "
        "WHERE id = ? AND status = 'processing' AND attempts = ?",
        (timestamp, job["id"], lease_attempt),
    ).rowcount
    if changed:
        database.execute(
            "UPDATE recordings SET transcript_status = 'completed', transcript_text = ?, transcript_error = NULL, "
            "transcribed_at = ? WHERE id = ?",
            (text.strip(), timestamp, job["recording_id"]),
        )


def fail(database, job: dict, error: Exception, max_attempts: int = 3, now: int | None = None) -> None:
    timestamp = now or int(time.time())
    attempts = int(job["attempts"]) + 1
    final = attempts >= max_attempts
    status = "failed" if final else "pending"
    retry_at = timestamp if final else timestamp + min(300, 15 * (2 ** max(0, attempts - 1)))
    message = str(error)[:500]
    changed = database.execute(
        "UPDATE transcription_jobs SET status = ?, available_at = ?, locked_at = NULL, last_error = ?, updated_at = ? "
        "WHERE id = ? AND status = 'processing' AND attempts = ?",
        (status, retry_at, message, timestamp, job["id"], attempts),
    ).rowcount
    if changed:
        database.execute(
            "UPDATE recordings SET transcript_status = ?, transcript_error = ? WHERE id = ?",
            (status, message, job["recording_id"]),
        )
