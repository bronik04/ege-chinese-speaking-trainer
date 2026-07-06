from __future__ import annotations

import json
import logging
import mimetypes
import os
import secrets
import sqlite3
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import quote, unquote

from api.errors import default_error_code, error_payload
from api.runtime import AUDIO_DIR, DATA_DIR, EMAIL_RE, MAX_BODY, ROOT, SESSION_DAYS, connect
from backend.accounts import record_audit
from backend.mailer import send_email
from backend.observability import log_event
from backend.security import request_has_same_origin, token_digest
from backend.storage import storage_from_env


class CommonControllerMixin:
    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        expires = now + SESSION_DAYS * 86400
        with connect() as database:
            database.execute(
                "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token_digest(token), user_id, expires, now),
            )
        return token

    def current_user(self) -> dict | None:
        token = self.session_token()
        if not token:
            return None
        with connect() as database:
            row = database.execute(
                """
                SELECT users.id, users.email, users.display_name, users.role, users.email_verified_at FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_digest(token), int(time.time())),
            ).fetchone()
        return (
            self.user_payload(row["id"], row["email"], row["display_name"], row["role"], row["email_verified_at"])
            if row
            else None
        )

    @staticmethod
    def user_payload(user_id: int, email: str, display_name: str, role: str, email_verified_at: int | None) -> dict:
        return {
            "id": user_id,
            "email": email,
            "displayName": display_name,
            "role": role,
            "emailVerified": email_verified_at is not None,
        }

    @staticmethod
    def user_for_token(database: sqlite3.Connection, token: str) -> sqlite3.Row | None:
        return database.execute(
            """
            SELECT users.id, users.email FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ?
            """,
            (token_digest(token),),
        ).fetchone()

    def audit(
        self,
        database: sqlite3.Connection,
        action: str,
        *,
        user_id: int | None = None,
        email: str | None = None,
        details: dict | None = None,
    ) -> None:
        record_audit(
            database,
            action,
            user_id=user_id,
            email=email,
            ip_address=self.client_address[0],
            user_agent=self.headers.get("User-Agent", ""),
            details=details,
        )

    def send_account_link(self, kind: str, email: str, token: str) -> str:
        public_url = os.environ.get("TRAINER_PUBLIC_URL", "").rstrip("/")
        if not public_url:
            origin = self.headers.get("Origin")
            public_url = origin.rstrip("/") if origin else f"http://{self.headers.get('Host', '127.0.0.1:8080')}"
        parameter = "verify" if kind == "email_verification" else "reset"
        url = f"{public_url}/?{parameter}={quote(token)}"
        if kind == "email_verification":
            subject = "Подтвердите email — тренажёр ЕГЭ"
            body = f"Подтвердите адрес электронной почты. Ссылка действует 24 часа:\n\n{url}"
        else:
            subject = "Восстановление пароля — тренажёр ЕГЭ"
            body = f"Создайте новый пароль. Ссылка действует 1 час:\n\n{url}"
        try:
            return send_email(DATA_DIR, email, subject, body)
        except Exception as error:
            with connect() as database:
                user = database.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                self.audit(
                    database,
                    "email_delivery_failed",
                    user_id=user["id"] if user else None,
                    email=email,
                    details={"kind": kind},
                )
            print(f"Email delivery failed: {type(error).__name__}")
            return "failed"

    @staticmethod
    def delete_audio_files(file_names: list[str]) -> None:
        storage = storage_from_env(AUDIO_DIR)
        for file_name in file_names:
            try:
                storage.delete(file_name)
            except Exception:
                continue

    def require_role(self, role: str) -> dict | None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return None
        if user["role"] != role:
            self.send_error_json(HTTPStatus.FORBIDDEN, "Недостаточно прав")
            return None
        return user

    def session_token(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("trainer_session")
        return morsel.value if morsel else None

    def validate_credentials(self, payload: dict) -> tuple[str, str, str | None]:
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if len(email) > 254 or not EMAIL_RE.match(email):
            return email, password, "Введите корректный email"
        if len(password) < 8 or len(password) > 128:
            return email, password, "Пароль должен содержать от 8 до 128 символов"
        return email, password, None

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
        if relative.startswith("data/variants/"):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found", "not_found")
            return
        candidate = (ROOT / relative).resolve()
        if ROOT not in candidate.parents and candidate != ROOT:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if candidate.is_dir():
            candidate /= "index.html"
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
