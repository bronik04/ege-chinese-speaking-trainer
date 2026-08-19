"""FastAPI route modules."""

from __future__ import annotations

from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from trainer.api import runtime
from trainer.api.cookies import cleared_session_cookie, session_cookie
from trainer.api.ranges import RangeNotSatisfiable, parse_single_byte_range
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


def file_response(stored: FileResult, range_header: str | None = None) -> Response:
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
    }
    try:
        byte_range = parse_single_byte_range(range_header, stored.size_bytes)
    except RangeNotSatisfiable:
        return Response(
            status_code=416,
            headers={**headers, "Content-Range": f"bytes */{stored.size_bytes}"},
        )

    # runtime.AUDIO_DIR читается как атрибут модуля, а не захватывается по
    # значению при импорте: тестовые фикстуры патчат именно runtime.AUDIO_DIR,
    # и захваченная копия осталась бы нацелена на боевой var/audio.
    path = storage_local_path(runtime.AUDIO_DIR, stored.key)
    if path is not None:
        return FileResponse(path, media_type=stored.mime_type, headers=headers)

    if byte_range is None:
        return StreamingResponse(
            stream_recording(runtime.AUDIO_DIR, stored.key),
            media_type=stored.mime_type,
            headers={**headers, "Content-Length": str(stored.size_bytes)},
        )

    return StreamingResponse(
        stream_recording(
            runtime.AUDIO_DIR,
            stored.key,
            start=byte_range.start,
            end=byte_range.end,
        ),
        status_code=206,
        media_type=stored.mime_type,
        headers={
            **headers,
            "Content-Range": f"bytes {byte_range.start}-{byte_range.end}/{stored.size_bytes}",
            "Content-Length": str(byte_range.length),
        },
    )
