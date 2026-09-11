from trainer.api import runtime
from trainer.api.errors import ApiError
from trainer.api.results import ActionResult
from trainer.api.schemas import ProgressRequest
from trainer.services.progress import ProgressError

_MESSAGES = {"invalid_document": "Invalid progress document", "history_too_large": "Progress history is too large"}


def _raise_progress_error(error: ProgressError, *, reading: bool = False) -> None:
    if reading and error.reason == "stored_document_invalid":
        raise ApiError(
            "progress_data_incompatible",
            "Сохранённый прогресс имеет несовместимый формат",
            409,
        ) from error
    message = _MESSAGES.get(error.reason)
    if message is None:
        raise error
    raise ApiError("invalid_request", message, 400) from error


def progress_get(user: dict) -> ActionResult:
    try:
        record = runtime.progress_service().get(user["id"])
    except ProgressError as error:
        _raise_progress_error(error, reading=True)
    return ActionResult(
        {
            "progress": record.document if record is not None else None,
            "updatedAt": record.updated_at if record is not None else None,
        }
    )


def progress_put(payload: ProgressRequest, user: dict) -> ActionResult:
    try:
        document = payload.progress.model_dump(mode="json", by_alias=True)
        updated_at = runtime.progress_service().put(user["id"], document)
    except ProgressError as error:
        _raise_progress_error(error)
    return ActionResult({"ok": True, "updatedAt": updated_at})
