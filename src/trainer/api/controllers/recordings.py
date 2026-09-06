from trainer.api import runtime
from trainer.api.errors import ApiError
from trainer.api.results import FileResult
from trainer.services.recording_access import RecordingAccessError
from trainer.services.recording_access_repository import RecordingActor, StoredFile

_ERRORS = {
    "legacy_recording_not_found": ("not_found", "Запись не найдена"),
    "review_recording_not_found": ("recording_not_found", "Запись не найдена"),
    "review_asset_not_found": ("asset_not_found", "Изображение не найдено"),
}


def _actor(user: dict) -> RecordingActor:
    return RecordingActor(
        user["id"],
        str(user.get("role", "")),
        str(user.get("email", "")),
        bool(user.get("emailVerified")),
    )


def _result(stored: StoredFile) -> FileResult:
    return FileResult(stored.storage_key, stored.mime_type, stored.size_bytes)


def _access(call) -> FileResult:
    try:
        return _result(call())
    except RecordingAccessError as error:
        public = _ERRORS.get(error.reason)
        if public is None:
            raise
        raise ApiError(public[0], public[1], 404) from error


def recording_get(recording_id: int, user: dict) -> FileResult:
    return _access(lambda: runtime.recording_access_service().legacy_recording(recording_id, _actor(user)))


def review_recording_get(recording_id: int, user: dict) -> FileResult:
    return _access(lambda: runtime.recording_access_service().review_recording(recording_id, _actor(user)))


def review_asset_get(asset_id: int, user: dict) -> FileResult:
    return _access(lambda: runtime.recording_access_service().review_asset(asset_id, _actor(user)))
