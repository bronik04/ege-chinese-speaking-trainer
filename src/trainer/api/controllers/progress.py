from trainer.api import runtime
from trainer.api.errors import ApiError
from trainer.api.results import ActionResult
from trainer.api.schemas import ProgressRequest
from trainer.services.progress import ProgressError

_MESSAGES = {"invalid_document": "Invalid progress document", "history_too_large": "Progress history is too large"}


def progress_get(user: dict) -> ActionResult:
    record = runtime.progress_service().get(user["id"])
    return ActionResult(
        {
            "progress": record.document if record is not None else None,
            "updatedAt": record.updated_at if record is not None else None,
        }
    )


def progress_put(payload: ProgressRequest, user: dict) -> ActionResult:
    try:
        updated_at = runtime.progress_service().put(user["id"], payload.progress)
    except ProgressError as error:
        message = _MESSAGES.get(error.reason)
        if message is None:
            raise
        raise ApiError("invalid_request", message, 400) from error
    return ActionResult({"ok": True, "updatedAt": updated_at})
