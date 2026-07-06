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
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.errors import default_error_code, error_payload
from api.routes import accounts, groups, recordings, work
from api.runtime import ROOT, init_database
from backend.database import close_connections, engine_name
from backend.observability import (
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
    return {"ok": True, "database": engine_name(), "errors": error_monitor.snapshot()}


@app.get("/{path:path}")
async def static_files(path: str):
    relative = unquote(path) or "index.html"
    candidate = (ROOT / relative).resolve()
    allowed = relative in {"index.html", "app.js", "styles.css", "variants.html", "variants.css"} or relative.startswith(
        ("assets/", "data/variants/", "js/")
    )
    if not allowed or (ROOT not in candidate.parents and candidate != ROOT) or not candidate.is_file():
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
