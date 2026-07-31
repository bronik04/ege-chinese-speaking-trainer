from __future__ import annotations

import json
import secrets
import subprocess
import tempfile
import time
from http import HTTPStatus
from pathlib import Path

from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import ActionResult, FileResult, RequestContext
from trainer.api.runtime import AUDIO_DIR, DATA_DIR, MAX_AUDIO_BODY, connect
from trainer.infrastructure.audio import validate_duration
from trainer.services import accounts as account_services
from trainer.services.recordings import delete_recordings, write_recording


def recording_create(
    submission_id: int, query: dict, body: bytes, content_type: str, user: dict, context: RequestContext
) -> ActionResult:
    try:
        task = int(query.get("task") or "")
        question_value = query.get("question")
        question = int(question_value) if question_value else None
    except (TypeError, ValueError) as error:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Некорректный номер записи", HTTPStatus.BAD_REQUEST
        ) from error
    label = str(query.get("label") or f"Задание {task}")[:160]
    mime_type = content_type.split(";", 1)[0].lower()
    extensions = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav"}
    if task not in {1, 2, 3} or mime_type not in extensions:
        raise ApiError(
            default_error_code(HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
            "Неподдерживаемый формат аудио",
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        )
    length = len(body)
    if not 0 < length <= MAX_AUDIO_BODY:
        raise ApiError(
            default_error_code(HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
            "Запись превышает 15 МБ",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    with connect() as database:
        row = database.execute(
            """
            SELECT submissions.id, assignments.tasks_json FROM submissions
            JOIN assignments ON assignments.id = submissions.assignment_id
            WHERE submissions.id = ? AND submissions.student_id = ?
            """,
            (submission_id, user["id"]),
        ).fetchone()
        if not row or task not in json.loads(row["tasks_json"]):
            raise ApiError(
                default_error_code(HTTPStatus.FORBIDDEN), "Запись не относится к этой попытке", HTTPStatus.FORBIDDEN
            )
    relative = f"{submission_id}/{secrets.token_urlsafe(18)}.{extensions[mime_type]}"
    temporary_dir = DATA_DIR / "tmp"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=temporary_dir, suffix=f".{extensions[mime_type]}", delete=False) as file:
        file.write(body)
        temporary_path = Path(file.name)
    try:
        duration = validate_duration(temporary_path, task)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        temporary_path.unlink(missing_ok=True)
        raise ApiError(
            default_error_code(HTTPStatus.UNPROCESSABLE_ENTITY),
            "Некорректная или слишком длинная аудиозапись",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        ) from error
    try:
        write_recording(AUDIO_DIR, relative, temporary_path, mime_type)
        with connect() as database:
            cursor = database.execute(
                """
                INSERT INTO recordings(submission_id, task_number, question_number, label, file_name, mime_type,
                                       size_bytes, duration_seconds, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    task,
                    question,
                    label,
                    relative,
                    mime_type,
                    len(body),
                    duration,
                    int(time.time()),
                ),
            )
            account_services.audit(
                database,
                "recording_uploaded",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                user_id=user["id"],
                email=user["email"],
                details={"submissionId": submission_id, "task": task, "size": len(body)},
            )
    except Exception:
        delete_recordings(AUDIO_DIR, [relative])
        raise
    finally:
        temporary_path.unlink(missing_ok=True)
    return ActionResult({"recording": {"id": cursor.lastrowid}}, status=HTTPStatus.CREATED)


def recording_get(recording_id: int, user: dict) -> FileResult:
    with connect() as database:
        row = database.execute(
            """
            SELECT recordings.file_name, recordings.mime_type, recordings.size_bytes,
                   submissions.student_id, assignments.teacher_id
            FROM recordings JOIN submissions ON submissions.id = recordings.submission_id
            JOIN assignments ON assignments.id = submissions.assignment_id
            WHERE recordings.id = ?
            """,
            (recording_id,),
        ).fetchone()
    if not row or user["id"] not in {row["student_id"], row["teacher_id"]}:
        raise ApiError(default_error_code(HTTPStatus.NOT_FOUND), "Запись не найдена", HTTPStatus.NOT_FOUND)
    return FileResult(key=row["file_name"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])
