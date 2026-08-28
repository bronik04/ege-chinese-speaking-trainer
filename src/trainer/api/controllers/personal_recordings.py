from __future__ import annotations

import sqlite3
import subprocess
import tempfile
from contextlib import suppress
from http import HTTPStatus
from pathlib import Path

from trainer.api import runtime
from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import ActionResult, FileResult, RequestContext
from trainer.api.schemas import PersonalRecordingUpload
from trainer.infrastructure.audio import validate_duration
from trainer.services.personal_recordings import (
    archive_key,
    create_personal_recording,
    list_personal_recordings,
    personal_recording_file,
)
from trainer.services.recordings import write_recording
from trainer.services.storage_cleanup import enqueue_cleanup_job

_EXTENSIONS = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav"}


def _enqueue_orphan(key: str) -> None:
    with suppress(Exception):
        with runtime.connect() as database:
            enqueue_cleanup_job(database, audio_keys=[key], material_keys=[], assignment_keys=[])


def personal_recording_create(
    payload: PersonalRecordingUpload,
    body: bytes,
    content_type: str,
    user: dict,
    _: RequestContext,
) -> ActionResult:
    mime_type = content_type.split(";", 1)[0].lower()
    extension = _EXTENSIONS.get(mime_type)
    if not extension:
        raise ApiError(
            default_error_code(HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
            "Неподдерживаемый формат аудио",
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        )
    if not 0 < len(body) <= runtime.MAX_AUDIO_BODY:
        raise ApiError(
            default_error_code(HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
            "Запись превышает 15 МБ",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )

    temporary_dir = runtime.DATA_DIR / "tmp"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=temporary_dir, suffix=f".{extension}", delete=False) as file:
        file.write(body)
        temporary_path = Path(file.name)
    try:
        duration = validate_duration(temporary_path, payload.taskNumber)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        temporary_path.unlink(missing_ok=True)
        raise ApiError(
            default_error_code(HTTPStatus.UNPROCESSABLE_ENTITY),
            "Некорректная или слишком длинная аудиозапись",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        ) from error

    storage_key = archive_key(user["id"], extension)
    try:
        write_recording(runtime.AUDIO_DIR, storage_key, temporary_path, mime_type)
        with runtime.connect() as database:
            try:
                recording = create_personal_recording(
                    database,
                    student_id=user["id"],
                    run_id=payload.runId,
                    variant_id=payload.variantId,
                    task_number=payload.taskNumber,
                    question_number=payload.questionNumber,
                    label=payload.label,
                    storage_key=storage_key,
                    mime_type=mime_type,
                    size_bytes=len(body),
                    duration_seconds=duration,
                )
            except sqlite3.IntegrityError as error:
                raise ApiError(
                    "personal_recording_exists", "Запись для этого задания уже сохранена", HTTPStatus.CONFLICT
                ) from error
    except Exception:
        _enqueue_orphan(storage_key)
        raise
    finally:
        temporary_path.unlink(missing_ok=True)
    return ActionResult({"recording": recording}, status=HTTPStatus.CREATED)


def personal_recordings_list(user: dict) -> ActionResult:
    with runtime.connect() as database:
        recordings = list_personal_recordings(database, user["id"])
    return ActionResult({"recordings": recordings})


def personal_recording_get(recording_id: int, user: dict) -> FileResult:
    with runtime.connect() as database:
        row = personal_recording_file(database, recording_id, user["id"])
    if not row:
        raise ApiError("recording_not_found", "Запись не найдена", HTTPStatus.NOT_FOUND)
    return FileResult(key=row["storage_key"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])
