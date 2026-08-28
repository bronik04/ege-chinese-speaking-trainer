from __future__ import annotations

import secrets
import time

from trainer.domain.recording_retention import expires_at
from trainer.infrastructure.database.core import begin_immediate


def archive_key(student_id: int, extension: str) -> str:
    return f"personal-recordings/{student_id}/{secrets.token_urlsafe(18)}.{extension}"


def create_personal_recording(
    database,
    *,
    student_id: int,
    run_id: str,
    variant_id: str,
    task_number: int,
    question_number: int,
    label: str,
    storage_key: str,
    mime_type: str,
    size_bytes: int,
    duration_seconds: float,
    created_at: int | None = None,
) -> dict:
    created = int(time.time()) if created_at is None else int(created_at)
    begin_immediate(database)
    cursor = database.execute(
        """INSERT INTO personal_recordings(
               student_id,run_id,variant_id,task_number,question_number,label,storage_key,
               mime_type,size_bytes,duration_seconds,created_at,expires_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            student_id,
            run_id,
            variant_id,
            task_number,
            question_number,
            label,
            storage_key,
            mime_type,
            size_bytes,
            duration_seconds,
            created,
            expires_at(created),
        ),
    )
    return recording_metadata(
        database.execute("SELECT * FROM personal_recordings WHERE id=?", (cursor.lastrowid,)).fetchone()
    )


def list_personal_recordings(database, student_id: int, *, now: int | None = None) -> list[dict]:
    moment = int(time.time()) if now is None else int(now)
    rows = database.execute(
        """SELECT * FROM personal_recordings
           WHERE student_id=? AND expires_at>?
           ORDER BY created_at DESC,id DESC""",
        (student_id, moment),
    ).fetchall()
    return [recording_metadata(row) for row in rows]


def personal_recording_file(database, recording_id: int, student_id: int, *, now: int | None = None) -> dict | None:
    moment = int(time.time()) if now is None else int(now)
    return database.execute(
        """SELECT storage_key,mime_type,size_bytes FROM personal_recordings
           WHERE id=? AND student_id=? AND expires_at>?""",
        (recording_id, student_id, moment),
    ).fetchone()


def recording_metadata(row) -> dict:
    return {
        "id": row["id"],
        "runId": row["run_id"],
        "variantId": row["variant_id"],
        "taskNumber": row["task_number"],
        "questionNumber": row["question_number"],
        "label": row["label"],
        "createdAt": row["created_at"],
        "expiresAt": row["expires_at"],
    }
