from trainer.api.dependencies import owner_email_from_env
from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import FileResult
from trainer.api.runtime import connect


def recording_get(recording_id: int, user: dict) -> FileResult:
    """Read a pre-migration assignment recording without exposing it in live UI."""
    with connect() as database:
        row = database.execute(
            """
            SELECT recordings.file_name, recordings.mime_type, recordings.size_bytes,
                   submissions.status, submissions.student_id, assignments.teacher_id
            FROM recordings JOIN submissions ON submissions.id = recordings.submission_id
            JOIN assignments ON assignments.id = submissions.assignment_id
            WHERE recordings.id = ?
            """,
            (recording_id,),
        ).fetchone()
    if (
        not row
        or user["id"] not in {row["student_id"], row["teacher_id"]}
        or (row["status"] == "uploading" and user["id"] != row["student_id"])
    ):
        raise ApiError(default_error_code(404), "Запись не найдена", 404)
    return FileResult(key=row["file_name"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])


def _review_file_allowed(row, user: dict) -> bool:
    if row["student_id"] == user["id"]:
        return True
    return bool(
        row["status"] in {"queued", "reviewed"}
        and user.get("role") == "teacher"
        and user.get("emailVerified")
        and str(user.get("email", "")).strip().lower() == owner_email_from_env()
    )


def review_recording_get(recording_id: int, user: dict) -> FileResult:
    with connect() as database:
        row = database.execute(
            """SELECT review_request_recordings.storage_key,review_request_recordings.mime_type,
                      review_request_recordings.size_bytes,review_requests.status,review_requests.student_id
               FROM review_request_recordings
               JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
               JOIN review_requests ON review_requests.id=review_request_items.request_id
               WHERE review_request_recordings.id=?""",
            (recording_id,),
        ).fetchone()
    if not row or not _review_file_allowed(row, user):
        raise ApiError("recording_not_found", "Запись не найдена", 404)
    return FileResult(key=row["storage_key"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])


def review_asset_get(asset_id: int, user: dict) -> FileResult:
    with connect() as database:
        row = database.execute(
            """SELECT review_request_assets.storage_key,review_request_assets.mime_type,
                      review_request_assets.size_bytes,review_requests.status,review_requests.student_id
               FROM review_request_assets
               JOIN review_requests ON review_requests.id=review_request_assets.request_id
               WHERE review_request_assets.id=?""",
            (asset_id,),
        ).fetchone()
    if not row or not _review_file_allowed(row, user):
        raise ApiError("asset_not_found", "Изображение не найдено", 404)
    return FileResult(key=row["storage_key"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])
