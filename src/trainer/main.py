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

from trainer.api.errors import default_error_code, error_payload
from trainer.api.routes import accounts, groups, materials, recordings, work
from trainer.api.runtime import MAX_BODY, ROOT, connect, init_database
from trainer.infrastructure.database.core import close_connections, engine_name
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
    try:
        yield
    finally:
        close_connections()


app = FastAPI(title="Тренажёр устной части ЕГЭ по китайскому", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(accounts.router)
app.include_router(groups.router)
app.include_router(work.router)
app.include_router(recordings.router)
app.include_router(materials.router)


@app.middleware("http")
async def reject_oversized_json(request, call_next):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        try:
            content_length = int(request.headers.get("content-length", ""))
        except ValueError:
            content_length = -1
        if content_length > MAX_BODY:
            return JSONResponse(
                error_payload("request_too_large", "Request body is too large"),
                status_code=413,
            )
        if content_length < 0:
            return JSONResponse(error_payload("length_required", "Content-Length is required"), status_code=411)
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
        return JSONResponse(
            {"ok": False, "database": engine_name(), "errors": error_monitor.snapshot()}, status_code=503
        )
    return {"ok": True, "database": engine_name(), "errors": error_monitor.snapshot()}


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
