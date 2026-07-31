"""FastAPI route modules."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from trainer.api.cookies import cleared_session_cookie, session_cookie
from trainer.api.results import ActionResult


def respond(result: ActionResult) -> JSONResponse:
    response = JSONResponse(result.payload, status_code=result.status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    for name, value in result.headers.items():
        response.headers[name] = value
    if result.session_token:
        response.headers["Set-Cookie"] = session_cookie(result.session_token)
    elif result.clear_session:
        response.headers["Set-Cookie"] = cleared_session_cookie()
    return response
