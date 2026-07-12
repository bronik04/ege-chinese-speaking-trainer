from __future__ import annotations

import time
from http import HTTPStatus

from trainer.api.errors import error_payload
from trainer.api.runtime import ASSIGNMENT_ASSET_DIR, MATERIAL_ASSET_DIR, connect
from trainer.domain.accounts import email_in_allowlist, password_hash, password_matches, token_digest
from trainer.infrastructure.database.accounts import (
    audit_events,
    clear_rate_limit,
    consume_rate_limit,
    consume_token,
    issue_token,
)
from trainer.infrastructure.database.core import INTEGRITY_ERRORS
from trainer.infrastructure.storage import storage_from_env


class AuthControllerMixin:
    def auth_register(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        email, password, error = self.validate_credentials(payload)
        if not self.allow_auth_attempt("register", email):
            return
        if error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, error)
            return
        role = str(payload.get("role", "student"))
        display_name = str(payload.get("displayName", "")).strip()
        if role not in {"student", "teacher"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Выберите тип аккаунта")
            return
        if not 2 <= len(display_name) <= 80:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Укажите имя длиной от 2 до 80 символов")
            return
        if role == "teacher" and not email_in_allowlist(email, "TRAINER_TEACHER_EMAILS"):
            self.send_error_json(HTTPStatus.FORBIDDEN, "Роль преподавателя недоступна", "teacher_not_allowed")
            return
        try:
            with connect() as database:
                cursor = database.execute(
                    "INSERT INTO users(email, password_hash, display_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (email, password_hash(password), display_name, role, int(time.time())),
                )
                user_id = cursor.lastrowid
                verification_token = issue_token(database, "email_verification", user_id)
                self.audit(database, "account_registered", user_id=user_id, email=email, details={"role": role})
        except INTEGRITY_ERRORS:
            self.send_error_json(
                HTTPStatus.CONFLICT, "Аккаунт с таким email уже существует", "email_already_registered"
            )
            return
        token = self.create_session(user_id)
        with connect() as database:
            clear_rate_limit(database, "register", self.client_address[0], email)
        delivery = self.send_account_link("email_verification", email, verification_token)
        self.send_json(
            {"user": self.user_payload(user_id, email, display_name, role, None), "verificationDelivery": delivery},
            HTTPStatus.CREATED,
            token,
        )

    def auth_login(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if not self.allow_auth_attempt("login", email):
            return
        with connect() as database:
            user = database.execute(
                "SELECT id, email, password_hash, display_name, role, email_verified_at FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        if not user or not password_matches(password, user["password_hash"]):
            with connect() as database:
                self.audit(database, "login_failed", user_id=user["id"] if user else None, email=email)
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Неверный email или пароль", "invalid_credentials")
            return
        token = self.create_session(user["id"])
        with connect() as database:
            clear_rate_limit(database, "login", self.client_address[0], email)
            self.audit(database, "login_succeeded", user_id=user["id"], email=email)
        self.send_json(
            {
                "user": self.user_payload(
                    user["id"], user["email"], user["display_name"], user["role"], user["email_verified_at"]
                )
            },
            token=token,
        )

    def allow_auth_attempt(self, kind: str, email: str) -> bool:
        with connect() as database:
            retry_after = consume_rate_limit(database, kind, self.client_address[0], email)
        if not retry_after:
            return True
        self.send_json(
            error_payload("rate_limited", "Слишком много попыток. Попробуйте позже", retryAfter=retry_after),
            HTTPStatus.TOO_MANY_REQUESTS,
            extra_headers={"Retry-After": str(retry_after)},
        )
        return False

    def auth_logout(self) -> None:
        token = self.session_token()
        if token:
            with connect() as database:
                user = self.user_for_token(database, token)
                if user:
                    self.audit(database, "logout", user_id=user["id"], email=user["email"])
                database.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))
        self.send_json({"ok": True}, clear_cookie=True)

    def auth_me(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        self.send_json({"user": user})

    def email_verification_request(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        if user["emailVerified"]:
            self.send_error_json(HTTPStatus.CONFLICT, "Email уже подтверждён", "email_already_verified")
            return
        if not self.allow_auth_attempt("email_verification", user["email"]):
            return
        with connect() as database:
            token = issue_token(database, "email_verification", user["id"])
            self.audit(database, "email_verification_requested", user_id=user["id"], email=user["email"])
        delivery = self.send_account_link("email_verification", user["email"], token)
        self.send_json({"ok": True, "delivery": delivery})

    def email_verification_confirm(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        token = str(payload.get("token", ""))
        with connect() as database:
            user = consume_token(database, "email_verification", token)
            if not user:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Ссылка недействительна или устарела", "token_invalid")
                return
            verified_at = int(time.time())
            database.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (verified_at, user["id"]))
            self.audit(database, "email_verified", user_id=user["id"], email=user["email"])
        self.send_json({"ok": True})

    def password_reset_request(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        email = str(payload.get("email", "")).strip().lower()
        if not self.allow_auth_attempt("password_reset", email):
            return
        with connect() as database:
            user = database.execute("SELECT id, email FROM users WHERE email = ?", (email,)).fetchone()
            if user:
                token = issue_token(database, "password_reset", user["id"])
                self.audit(database, "password_reset_requested", user_id=user["id"], email=email)
            else:
                token = None
                self.audit(database, "password_reset_requested_unknown", email=email)
        if token:
            self.send_account_link("password_reset", email, token)
        self.send_json({"ok": True, "message": "Если аккаунт существует, инструкция отправлена"})

    def password_reset_confirm(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        token = str(payload.get("token", ""))
        password = str(payload.get("password", ""))
        if not 8 <= len(password) <= 128:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Пароль должен содержать от 8 до 128 символов")
            return
        with connect() as database:
            user = consume_token(database, "password_reset", token)
            if not user:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Ссылка недействительна или устарела", "token_invalid")
                return
            database.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash(password), user["id"]))
            database.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
            clear_rate_limit(database, "login", self.client_address[0], user["email"])
            self.audit(database, "password_reset_completed", user_id=user["id"], email=user["email"])
        self.send_json({"ok": True}, clear_cookie=True)

    def account_audit(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        with connect() as database:
            events = audit_events(database, user["id"])
        self.send_json({"events": events})

    def account_delete(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        payload = self.read_json()
        if payload is None:
            return
        password = str(payload.get("password", ""))
        with connect() as database:
            row = database.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
            if not row or not password_matches(password, row["password_hash"]):
                self.audit(database, "account_deletion_failed", user_id=user["id"], email=user["email"])
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Неверный пароль", "invalid_password")
                return
            files = database.execute(
                """
                SELECT recordings.file_name FROM recordings
                JOIN submissions ON submissions.id = recordings.submission_id
                JOIN assignments ON assignments.id = submissions.assignment_id
                WHERE submissions.student_id = ? OR assignments.teacher_id = ?
                """,
                (user["id"], user["id"]),
            ).fetchall()
            material_assets = database.execute(
                """SELECT material_assets.storage_key FROM material_assets
                   JOIN materials ON materials.id=material_assets.material_id
                   WHERE materials.owner_id=?""",
                (user["id"],),
            ).fetchall()
            assignment_assets = database.execute(
                """SELECT assignment_material_assets.storage_key FROM assignment_material_assets
                   JOIN assignments ON assignments.id=assignment_material_assets.assignment_id
                   WHERE assignments.teacher_id=?""",
                (user["id"],),
            ).fetchall()
            self.audit(database, "account_deleted", user_id=user["id"], email=user["email"])
            database.execute("DELETE FROM users WHERE id = ?", (user["id"],))
        self.delete_audio_files([row["file_name"] for row in files])
        storage = storage_from_env(MATERIAL_ASSET_DIR)
        for asset in material_assets:
            try:
                storage.delete(asset["storage_key"])
            except Exception:
                continue
        assignment_storage = storage_from_env(ASSIGNMENT_ASSET_DIR)
        for asset in assignment_assets:
            try:
                assignment_storage.delete(asset["storage_key"])
            except Exception:
                continue
        self.send_json({"ok": True}, clear_cookie=True)
