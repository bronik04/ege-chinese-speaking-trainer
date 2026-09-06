import sqlite3
from collections.abc import Callable
from contextlib import closing

from trainer.services.recording_access_repository import (
    LegacyRecordingRecord,
    ReviewAssetRecord,
    ReviewRecordingRecord,
    StoredFile,
)


class SQLiteRecordingAccessRepository:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self._connect = connect

    def legacy_recording(self, recording_id: int) -> LegacyRecordingRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT recordings.file_name,recordings.mime_type,recordings.size_bytes,
                          submissions.status,submissions.student_id,assignments.teacher_id
                   FROM recordings
                   JOIN submissions ON submissions.id=recordings.submission_id
                   JOIN assignments ON assignments.id=submissions.assignment_id
                   WHERE recordings.id=?""",
                (recording_id,),
            ).fetchone()
        return (
            LegacyRecordingRecord(
                StoredFile(row["file_name"], row["mime_type"], row["size_bytes"]),
                row["status"],
                row["student_id"],
                row["teacher_id"],
            )
            if row
            else None
        )

    def review_recording(self, recording_id: int) -> ReviewRecordingRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT review_request_recordings.storage_key,
                          review_request_recordings.mime_type,
                          review_request_recordings.size_bytes,
                          review_request_recordings.expires_at,
                          review_requests.status,review_requests.student_id
                   FROM review_request_recordings
                   JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
                   JOIN review_requests ON review_requests.id=review_request_items.request_id
                   WHERE review_request_recordings.id=?""",
                (recording_id,),
            ).fetchone()
        return (
            ReviewRecordingRecord(
                StoredFile(row["storage_key"], row["mime_type"], row["size_bytes"]),
                row["status"],
                row["student_id"],
                row["expires_at"],
            )
            if row
            else None
        )

    def review_asset(self, asset_id: int) -> ReviewAssetRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT review_request_assets.storage_key,review_request_assets.mime_type,
                          review_request_assets.size_bytes,review_requests.status,
                          review_requests.student_id
                   FROM review_request_assets
                   JOIN review_requests ON review_requests.id=review_request_assets.request_id
                   WHERE review_request_assets.id=?""",
                (asset_id,),
            ).fetchone()
        return (
            ReviewAssetRecord(
                StoredFile(row["storage_key"], row["mime_type"], row["size_bytes"]),
                row["status"],
                row["student_id"],
            )
            if row
            else None
        )
