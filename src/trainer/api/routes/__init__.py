"""FastAPI route modules."""

from __future__ import annotations

from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from trainer.api import runtime
from trainer.api.cookies import cleared_session_cookie, session_cookie
from trainer.api.results import ActionResult, FileResult
from trainer.services.recordings import storage_local_path, stream_recording


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


def file_response(stored: FileResult, cache_control: str = "private, no-store") -> Response:
    headers = {"Cache-Control": cache_control, "X-Content-Type-Options": "nosniff"}
    # runtime.AUDIO_DIR читается как атрибут модуля, а не захватывается по
    # значению при импорте: тестовые фикстуры патчат именно runtime.AUDIO_DIR,
    # и захваченная копия осталась бы нацелена на боевой var/audio.
    path = storage_local_path(runtime.AUDIO_DIR, stored.key)
    if path is not None:
        return FileResponse(path, media_type=stored.mime_type, headers=headers)
    return StreamingResponse(
        stream_recording(runtime.AUDIO_DIR, stored.key), media_type=stored.mime_type, headers=headers
    )
