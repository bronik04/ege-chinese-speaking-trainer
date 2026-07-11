from __future__ import annotations

import json
import logging
import mimetypes
import os
from http import HTTPStatus
from urllib.parse import unquote

from trainer.api.errors import default_error_code, error_payload
from trainer.api.runtime import DATA_DIR, MAX_BODY, ROOT, SESSION_DAYS
from trainer.api.security import request_has_same_origin
from trainer.infrastructure.observability import log_event


class ApiTransportMixin:
    def read_json(self) -> dict | None:
        validated = getattr(self, "validated_payload", None)
        if validated is not None:
            return dict(validated)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid request body")
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return None
        if not isinstance(payload, dict):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "JSON object required")
            return None
        return payload

    def same_origin_request(self) -> bool:
        return request_has_same_origin(
            self.headers.get("Host"),
            self.headers.get("Origin"),
            self.headers.get("Referer"),
            self.headers.get("Sec-Fetch-Site"),
        )

    def serve_static(self, route: str) -> None:
        relative = unquote(route).lstrip("/") or "index.html"
        pages = {"index.html", "about.html", "reference.html", "variants.html", "variant-editor.html"}
        if relative in pages:
            base, resource = ROOT / "frontend/pages", relative
        elif relative.startswith(("js/", "styles/")):
            base, resource = ROOT / "frontend", relative
        elif relative.startswith("assets/"):
            base, resource = ROOT / "public", relative
        elif relative.startswith("content/reference/"):
            base, resource = ROOT / "content/reference", relative.removeprefix("content/reference/")
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found", "not_found")
            return
        base = base.resolve()
        candidate = (base / resource).resolve()
        if base not in candidate.parents and candidate != base:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file() or candidate == DATA_DIR or DATA_DIR in candidate.parents:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type
        )
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Cache-Control",
            "no-cache" if candidate.suffix in {".html", ".js", ".css", ".json"} else "public, max-age=86400",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(data)

    def send_json(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
        token: str | None = None,
        clear_cookie: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        if token:
            cookie = f"trainer_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"
            if os.environ.get("TRAINER_SECURE_COOKIE") == "1":
                cookie += "; Secure"
            self.send_header("Set-Cookie", cookie)
        elif clear_cookie:
            self.send_header("Set-Cookie", "trainer_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
        self.end_headers()
        self.wfile.write(encoded)

    def send_error_json(self, status: HTTPStatus, message: str, code: str | None = None) -> None:
        resolved_code = code or default_error_code(status)
        log_event(
            logging.getLogger("trainer.api"),
            logging.WARNING if int(status) < 500 else logging.ERROR,
            "api_error",
            message,
            code=resolved_code,
            status=int(status),
            path=getattr(self, "path", ""),
        )
        self.send_json(error_payload(resolved_code, message), status)

    def send_bytes(self, data: bytes, content_type: str, filename: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:
        log_event(
            logging.getLogger("trainer.compat_http"),
            logging.INFO,
            "request_completed",
            fmt % args,
            client=self.address_string(),
        )
