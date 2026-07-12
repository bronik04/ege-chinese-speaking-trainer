from __future__ import annotations

import os
import secrets
import sqlite3
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import quote

from trainer.api.runtime import AUDIO_DIR, DATA_DIR, EMAIL_RE, SESSION_DAYS, connect
from trainer.domain.accounts import email_in_allowlist, token_digest
from trainer.infrastructure.database.accounts import record_audit
from trainer.infrastructure.mailer import send_email
from trainer.infrastructure.storage import storage_from_env


def account_public_url() -> str:
    return os.environ.get("TRAINER_PUBLIC_URL", "").rstrip("/") or "http://127.0.0.1:8080"


class ApiDependenciesMixin:
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
        public_url = account_public_url()
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
        if role == "teacher" and not user["emailVerified"]:
            self.send_error_json(
                HTTPStatus.FORBIDDEN,
                "Подтвердите email для доступа к кабинету преподавателя",
                "email_verification_required",
            )
            return None
        if role == "teacher" and not email_in_allowlist(user["email"], "TRAINER_TEACHER_EMAILS"):
            self.send_error_json(HTTPStatus.FORBIDDEN, "Роль преподавателя недоступна", "teacher_not_allowed")
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
