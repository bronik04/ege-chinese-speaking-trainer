from __future__ import annotations

import logging
import os
import re
import time
from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from trainer.api.body_limit import BodyLimitMiddleware
from trainer.api.errors import ApiError, api_error_handler, default_error_code, error_payload
from trainer.api.routes import accounts, groups, materials, recordings, work
from trainer.api.runtime import MAX_AUDIO_BODY, MAX_BODY, ROOT, connect, init_database
from trainer.api.security import request_has_same_origin
from trainer.infrastructure.observability import (
    configure_logging,
    current_request_id,
    error_monitor,
    log_event,
    reset_request_id,
    set_request_id,
)

configure_logging()
logger = logging.getLogger("trainer.http")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    yield


app = FastAPI(title="Тренажёр устной части ЕГЭ по китайскому", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_exception_handler(ApiError, api_error_handler)
app.include_router(accounts.router)
app.include_router(groups.router)
app.include_router(work.router)
app.include_router(recordings.router)
app.include_router(materials.router)


BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
RECORDING_UPLOAD_PATH = re.compile(r"^/api/submissions/\d+/recordings$")
MATERIAL_ASSET_UPLOAD_PATH = re.compile(r"^/api/materials/\d+/assets$")
MAX_MATERIAL_ASSET_BODY = 5_000_000


def _body_limit_for_request(method: str, path: str) -> int | None:
    if method not in BODY_METHODS:
        return None
    if RECORDING_UPLOAD_PATH.match(path):
        return MAX_AUDIO_BODY
    if MATERIAL_ASSET_UPLOAD_PATH.match(path):
        return MAX_MATERIAL_ASSET_BODY
    return MAX_BODY


app.add_middleware(BodyLimitMiddleware, limit_for_request=_body_limit_for_request)


def _matches_registered_route(request) -> bool:
    # Проверяем только запросы, которые реально дойдут до обработчика: иначе
    # запрос методом без зарегистрированного маршрута (например PUT на GET-only
    # путь) перехватывался бы здесь с 403 вместо штатного 404/405 от роутера.
    return any(route.matches(request.scope)[0] == Match.FULL for route in app.router.routes)


@app.middleware("http")
async def reject_cross_origin_writes(request, call_next):
    if (
        request.method in {"POST", "PUT", "DELETE"}
        and _matches_registered_route(request)
        and not request_has_same_origin(
            request.headers.get("Host"),
            request.headers.get("Origin"),
            request.headers.get("Referer"),
            request.headers.get("Sec-Fetch-Site"),
        )
    ):
        return JSONResponse(error_payload("invalid_origin", "Invalid request origin"), status_code=403)
    return await call_next(request)


@app.middleware("http")
async def reject_oversized_body(request, call_next):
    if request.method in BODY_METHODS:
        # Отсутствующий или нечисловой Content-Length не отвергаем: так приходят
        # chunked-запросы, а GET с JSON-заголовком вообще не несёт тела.
        # Фактический размер в любом случае считает потоковый ASGI middleware.
        limit = _body_limit_for_request(request.method, request.url.path)
        assert limit is not None
        raw_length = request.headers.get("content-length", "")
        if raw_length.isdigit() and int(raw_length) > limit:
            return JSONResponse(
                error_payload("request_too_large", "Request body is too large"),
                status_code=413,
            )
    return await call_next(request)


@app.middleware("http")
async def observe_requests(request, call_next):
    supplied_id = request.headers.get("X-Request-ID", "")
    request_id = supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{8,64}", supplied_id) else None
    request_token = set_request_id(request_id)
    started = time.perf_counter()
    try:
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request error",
                extra={"event": "request_failed", "fields": {"method": request.method, "path": request.url.path}},
            )
            response = JSONResponse(
                error_payload("internal_server_error", "Внутренняя ошибка сервера"),
                status_code=500,
            )
        status = response.status_code
        error_monitor.observe(status)
        level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
        log_event(
            logger,
            level,
            "request_completed",
            "Request completed",
            method=request.method,
            path=request.url.path,
            status=status,
            durationMs=round((time.perf_counter() - started) * 1000, 2),
        )
        response.headers["X-Request-ID"] = current_request_id()
        return response
    finally:
        reset_request_id(request_token)


@app.exception_handler(RequestValidationError)
async def validation_error(_, error: RequestValidationError):
    fields = [
        {"location": ".".join(str(part) for part in item["loc"] if part != "body"), "message": item["msg"]}
        for item in error.errors()
    ]
    return JSONResponse(
        error_payload("request_validation_failed", "Некорректные данные запроса", fields=fields),
        status_code=422,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(_, error: StarletteHTTPException):
    code = "method_not_allowed" if error.status_code == 405 else default_error_code(error.status_code)
    return JSONResponse(error_payload(code, str(error.detail)), status_code=error.status_code)


@app.get("/api/health")
async def health():
    try:
        await run_in_threadpool(_check_database)
    except Exception:
        return JSONResponse({"ok": False, "errors": error_monitor.snapshot()}, status_code=503)
    return {"ok": True, "errors": error_monitor.snapshot()}


def _check_database() -> None:
    with connect() as database:
        database.execute("SELECT 1").fetchone()


@app.get("/{path:path}")
async def static_files(path: str):
    relative = unquote(path) or "index.html"
    pages = {
        "index.html",
        "variants.html",
        "variant-editor.html",
        "reference.html",
        "about.html",
    }
    if relative in pages:
        base, resource = ROOT / "frontend/pages", relative
    elif relative.startswith("js/"):
        base, resource = ROOT / "frontend", relative
    elif relative.startswith("styles/"):
        base, resource = ROOT / "frontend", relative
    elif relative.startswith("assets/"):
        base, resource = ROOT / "public", relative
    elif relative.startswith("content/reference/"):
        base, resource = ROOT / "content/reference", relative.removeprefix("content/reference/")
    else:
        return JSONResponse(error_payload("not_found", "Not found"), status_code=404)
    candidate = (base / resource).resolve()
    if (base.resolve() not in candidate.parents and candidate != base.resolve()) or not candidate.is_file():
        return JSONResponse(error_payload("not_found", "Not found"), status_code=404)
    cache = "no-cache" if candidate.suffix in {".html", ".js", ".css", ".json"} else "public, max-age=86400"
    return FileResponse(candidate, headers={"Cache-Control": cache, "X-Content-Type-Options": "nosniff"})


def main() -> None:
    import uvicorn

    uvicorn.run(
        "asgi:app",
        host=os.environ.get("TRAINER_HOST", "127.0.0.1"),
        port=int(os.environ.get("TRAINER_PORT", "8080")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
