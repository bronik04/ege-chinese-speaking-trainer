from __future__ import annotations

import os
from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from api.routes import accounts, groups, recordings, work
from api.runtime import ROOT, init_database
from backend.database import close_connections, engine_name


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


@app.exception_handler(RequestValidationError)
async def validation_error(_, error: RequestValidationError):
    fields = [
        {"location": ".".join(str(part) for part in item["loc"] if part != "body"), "message": item["msg"]}
        for item in error.errors()
    ]
    return JSONResponse(
        {"error": "Некорректные данные запроса", "fields": fields},
        status_code=422,
    )


@app.get("/api/health")
async def health():
    return {"ok": True, "database": engine_name()}


@app.get("/{path:path}")
async def static_files(path: str):
    relative = unquote(path) or "index.html"
    candidate = (ROOT / relative).resolve()
    allowed = relative in {"index.html", "app.js", "styles.css"} or relative.startswith(
        ("assets/", "data/variants/", "js/")
    )
    if not allowed or (ROOT not in candidate.parents and candidate != ROOT) or not candidate.is_file():
        return JSONResponse({"error": "Not found"}, status_code=404)
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
