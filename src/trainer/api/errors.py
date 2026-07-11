from __future__ import annotations

from http import HTTPStatus

from trainer.infrastructure.observability import current_request_id

DEFAULT_CODES = {
    HTTPStatus.BAD_REQUEST: "invalid_request",
    HTTPStatus.UNAUTHORIZED: "authentication_required",
    HTTPStatus.FORBIDDEN: "forbidden",
    HTTPStatus.NOT_FOUND: "not_found",
    HTTPStatus.CONFLICT: "conflict",
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "request_too_large",
    HTTPStatus.UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    HTTPStatus.UNPROCESSABLE_ENTITY: "validation_failed",
    HTTPStatus.TOO_MANY_REQUESTS: "rate_limited",
    HTTPStatus.INTERNAL_SERVER_ERROR: "internal_server_error",
}


def error_payload(code: str, message: str, **details: object) -> dict:
    payload = {"code": code, "message": message}
    if request_id := current_request_id():
        payload["requestId"] = request_id
    payload.update(details)
    return payload


def default_error_code(status: int | HTTPStatus) -> str:
    try:
        resolved = HTTPStatus(status)
    except ValueError:
        return "request_failed"
    return DEFAULT_CODES.get(resolved, f"http_{resolved.value}")
