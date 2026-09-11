from __future__ import annotations

from http import HTTPStatus

from trainer.api import runtime
from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import ActionResult, FileResult, RequestContext
from trainer.api.schemas import PersonalRecordingUpload
from trainer.services.personal_recording_repository import PersonalRecordingData
from trainer.services.personal_recordings import PersonalRecordingError

_ERRORS = {
    "invalid_position": (HTTPStatus.BAD_REQUEST, None),
    "unsupported_audio": (HTTPStatus.UNSUPPORTED_MEDIA_TYPE, None),
    "audio_too_large": (HTTPStatus.REQUEST_ENTITY_TOO_LARGE, None),
    "invalid_audio": (HTTPStatus.UNPROCESSABLE_ENTITY, None),
    "recording_exists": (HTTPStatus.CONFLICT, "personal_recording_exists"),
    "recording_not_found": (HTTPStatus.NOT_FOUND, "recording_not_found"),
}


def _service_error(error: PersonalRecordingError) -> ApiError:
    mapping = _ERRORS.get(error.reason)
    if mapping is None:
        raise error
    status, code = mapping
    return ApiError(code or default_error_code(status), error.message, status)


def personal_recording_create(
    payload: PersonalRecordingUpload,
    body: bytes,
    content_type: str,
    user: dict,
    _: RequestContext,
) -> ActionResult:
    data = PersonalRecordingData(
        payload.runId,
        payload.variantId,
        payload.taskNumber,
        payload.questionNumber,
        payload.label,
    )
    try:
        recording = runtime.personal_recording_service().create(user["id"], data, body, content_type)
    except PersonalRecordingError as error:
        raise _service_error(error) from error
    return ActionResult({"recording": recording}, status=HTTPStatus.CREATED)


def personal_recordings_list(user: dict) -> ActionResult:
    return ActionResult({"recordings": runtime.personal_recording_service().list(user["id"])})


def personal_recording_get(recording_id: int, user: dict) -> FileResult:
    try:
        access = runtime.personal_recording_service().file(recording_id, user["id"])
    except PersonalRecordingError as error:
        raise _service_error(error) from error
    return FileResult(key=access.storage_key, mime_type=access.mime_type, size_bytes=access.size_bytes)
