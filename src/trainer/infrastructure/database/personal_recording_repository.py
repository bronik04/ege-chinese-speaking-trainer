from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing

from trainer.domain.recording_retention import expires_at
from trainer.infrastructure.database.core import INTEGRITY_ERRORS, begin_immediate
from trainer.services.personal_recording_repository import (
    PersonalRecordingAccess,
    PersonalRecordingConflictError,
    PersonalRecordingData,
    PersonalRecordingIntentError,
    PersonalRecordingRecord,
)
from trainer.services.storage_cleanup import enqueue_cleanup_job


def _record(row: sqlite3.Row) -> PersonalRecordingRecord:
    return PersonalRecordingRecord(
        row["id"],
        row["run_id"],
        row["variant_id"],
        row["task_number"],
        row["question_number"],
        row["label"],
        row["created_at"],
        row["expires_at"],
    )


class SQLitePersonalRecordingRepository:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self._connect = connect

    def create_upload_intent(self, storage_key: str, now: int, available_at: int) -> int:
        with closing(self._connect()) as database:
            try:
                cleanup_job_id = enqueue_cleanup_job(
                    database,
                    audio_keys=[storage_key],
                    material_keys=[],
                    assignment_keys=[],
                    now=now,
                    available_at=available_at,
                )
                database.commit()
                return cleanup_job_id
            except BaseException:
                database.rollback()
                raise

    def finalize_recording(
        self,
        student_id: int,
        data: PersonalRecordingData,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        duration_seconds: float,
        cleanup_job_id: int,
        now: int,
    ) -> PersonalRecordingRecord:
        with closing(self._connect()) as database:
            try:
                begin_immediate(database)
                cursor = database.execute(
                    """INSERT INTO personal_recordings(
                           student_id,run_id,variant_id,task_number,question_number,label,storage_key,
                           mime_type,size_bytes,duration_seconds,created_at,expires_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        student_id,
                        data.run_id,
                        data.variant_id,
                        data.task_number,
                        data.question_number,
                        data.label,
                        storage_key,
                        mime_type,
                        size_bytes,
                        duration_seconds,
                        now,
                        expires_at(now),
                    ),
                )
                deleted = database.execute(
                    "DELETE FROM storage_cleanup_jobs WHERE id=?",
                    (cleanup_job_id,),
                )
                if deleted.rowcount != 1:
                    raise PersonalRecordingIntentError("upload cleanup intent is missing")
                row = database.execute(
                    """SELECT id,run_id,variant_id,task_number,question_number,label,created_at,expires_at
                       FROM personal_recordings WHERE id=?""",
                    (cursor.lastrowid,),
                ).fetchone()
                database.commit()
                return _record(row)
            except INTEGRITY_ERRORS as error:
                database.rollback()
                raise PersonalRecordingConflictError from error
            except BaseException:
                database.rollback()
                raise

    def recordings(self, student_id: int, now: int) -> list[PersonalRecordingRecord]:
        with closing(self._connect()) as database:
            rows = database.execute(
                """SELECT id,run_id,variant_id,task_number,question_number,label,created_at,expires_at
                   FROM personal_recordings
                   WHERE student_id=? AND expires_at>?
                   ORDER BY created_at DESC,id DESC""",
                (student_id, now),
            ).fetchall()
        return [_record(row) for row in rows]

    def recording_file(
        self,
        recording_id: int,
        student_id: int,
        now: int,
    ) -> PersonalRecordingAccess | None:
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT storage_key,mime_type,size_bytes FROM personal_recordings
                   WHERE id=? AND student_id=? AND expires_at>?""",
                (recording_id, student_id, now),
            ).fetchone()
        if row is None:
            return None
        return PersonalRecordingAccess(row["storage_key"], row["mime_type"], row["size_bytes"])
