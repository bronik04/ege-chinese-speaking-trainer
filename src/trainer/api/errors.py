from __future__ import annotations

import logging
from http import HTTPStatus

from fastapi.responses import JSONResponse

from trainer.infrastructure.observability import current_request_id, log_event

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


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        *,
        headers: dict[str, str] | None = None,
        **details: object,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.headers = headers or {}
        self.details = details


async def api_error_handler(request, error: ApiError) -> JSONResponse:
    log_event(
        logging.getLogger("trainer.api"),
        logging.WARNING if error.status < 500 else logging.ERROR,
        "api_error",
        error.message,
        code=error.code,
        status=error.status,
        path=request.url.path,
    )
    response = JSONResponse(error_payload(error.code, error.message, **error.details), status_code=error.status)
    for name, value in error.headers.items():
        response.headers[name] = value
    return response
