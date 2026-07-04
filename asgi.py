from __future__ import annotations

import io
import os
from contextlib import asynccontextmanager
from types import MethodType
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

import server as legacy


@asynccontextmanager
async def lifespan(_: FastAPI):
    legacy.init_database()
    yield


app = FastAPI(title="Тренажёр устной части ЕГЭ по китайскому", docs_url=None, redoc_url=None, lifespan=lifespan)


def _bind(handler, name, function):
    setattr(handler, name, MethodType(function, handler))


async def dispatch(request: Request) -> Response:
    max_body = legacy.MAX_AUDIO_BODY if "/recordings" in request.url.path else legacy.MAX_BODY
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_body:
            return JSONResponse({"error": "Request body is too large"}, status_code=413)

    handler = object.__new__(legacy.TrainerHandler)
    handler.path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    handler.headers = request.headers
    handler.client_address = (request.client.host if request.client else "", 0)
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    state = {"status": 200, "headers": []}

    _bind(handler, "send_response", lambda self, status, message=None: state.update(status=int(status)))
    _bind(handler, "send_header", lambda self, name, value: state["headers"].append((name, value)))
    _bind(handler, "end_headers", lambda self: None)
    method = getattr(handler, f"do_{request.method}", None)
    if method is None:
        return JSONResponse({"error": "Method not allowed"}, status_code=405)
    method()
    return Response(content=handler.wfile.getvalue(), status_code=state["status"], headers=dict(state["headers"]))


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def api_dispatch(request: Request, path: str):
    return await dispatch(request)


@app.get("/{path:path}")
async def static_files(path: str):
    relative = unquote(path) or "index.html"
    candidate = (legacy.ROOT / relative).resolve()
    allowed = relative in {"index.html", "app.js", "styles.css"} or relative.startswith(("assets/", "data/variants/", "js/"))
    if not allowed or (legacy.ROOT not in candidate.parents and candidate != legacy.ROOT) or not candidate.is_file():
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
