from __future__ import annotations

import logging
import os
import time
from http import HTTPStatus

from trainer.api import runtime
from trainer.api.dependencies import account_public_url
from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import ActionResult, RequestContext
from trainer.api.runtime import SESSION_DAYS, connect
from trainer.api.schemas import (
    DeleteAccountRequest,
    EmailRequest,
    LoginRequest,
    PasswordResetRequest,
    RegisterRequest,
    TokenRequest,
)
from trainer.domain.accounts import (
    email_in_allowlist,
    password_hash,
    password_matches,
    token_digest,
    validate_credentials,
)
from trainer.infrastructure.database.accounts import (
    audit_events,
    clear_rate_limit,
    consume_rate_limit,
    consume_token,
    issue_token,
)
from trainer.infrastructure.database.core import INTEGRITY_ERRORS
from trainer.services import accounts as account_services
from trainer.services.accounts import delete_account_storage


def _ensure_auth_attempt_allowed(kind: str, email: str, client_ip: str) -> None:
    with connect() as database:
        retry_after = consume_rate_limit(database, kind, client_ip, email)
    if retry_after:
        raise ApiError(
            "rate_limited",
            "Слишком много попыток. Попробуйте позже",
            HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
            retryAfter=retry_after,
        )


def auth_register(payload: RegisterRequest, context: RequestContext) -> ActionResult:
    email, password, error = validate_credentials(payload.email, payload.password)
    _ensure_auth_attempt_allowed("register", email, context.client_ip)
    if error:
        raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), error, HTTPStatus.BAD_REQUEST)
    role = payload.role
    display_name = payload.displayName.strip()
    if role not in {"student", "teacher"}:
        raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), "Выберите тип аккаунта", HTTPStatus.BAD_REQUEST)
    if not 2 <= len(display_name) <= 80:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST),
            "Укажите имя длиной от 2 до 80 символов",
            HTTPStatus.BAD_REQUEST,
        )
    if role == "teacher" and not email_in_allowlist(email, os.environ.get("TRAINER_TEACHER_EMAILS", "")):
        raise ApiError("teacher_not_allowed", "Роль преподавателя недоступна", HTTPStatus.FORBIDDEN)
    try:
        with connect() as database:
            cursor = database.execute(
                "INSERT INTO users(email, password_hash, display_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (email, password_hash(password), display_name, role, int(time.time())),
            )
            user_id = cursor.lastrowid
            verification_token = issue_token(database, "email_verification", user_id)
            account_services.audit(
                database,
                "account_registered",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                user_id=user_id,
                email=email,
                details={"role": role},
            )
    except INTEGRITY_ERRORS as error:
        raise ApiError(
            "email_already_registered", "Аккаунт с таким email уже существует", HTTPStatus.CONFLICT
        ) from error
    token = account_services.create_session(connect, user_id, SESSION_DAYS)
    with connect() as database:
        clear_rate_limit(database, "register", context.client_ip, email)
    delivery = account_services.send_account_link(
        connect,
        runtime.DATA_DIR,
        "email_verification",
        email,
        verification_token,
        public_url=account_public_url(),
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    return ActionResult(
        {
            "user": account_services.user_payload(user_id, email, display_name, role, None),
            "verificationDelivery": delivery,
        },
        status=HTTPStatus.CREATED,
        session_token=token,
    )


def auth_login(payload: LoginRequest, context: RequestContext) -> ActionResult:
    email = payload.email.strip().lower()
    password = payload.password
    _ensure_auth_attempt_allowed("login", email, context.client_ip)
    with connect() as database:
        user = database.execute(
            "SELECT id, email, password_hash, display_name, role, email_verified_at FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if not user or not password_matches(password, user["password_hash"]):
        with connect() as database:
            account_services.audit(
                database,
                "login_failed",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                user_id=user["id"] if user else None,
                email=email,
            )
        raise ApiError("invalid_credentials", "Неверный email или пароль", HTTPStatus.UNAUTHORIZED)
    token = account_services.create_session(connect, user["id"], SESSION_DAYS)
    with connect() as database:
        clear_rate_limit(database, "login", context.client_ip, email)
        account_services.audit(
            database,
            "login_succeeded",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=email,
        )
    return ActionResult(
        {
            "user": account_services.user_payload(
                user["id"], user["email"], user["display_name"], user["role"], user["email_verified_at"]
            )
        },
        session_token=token,
    )


def auth_logout(token: str | None, context: RequestContext) -> ActionResult:
    if token:
        with connect() as database:
            user = account_services.user_for_token(database, token)
            if user:
                account_services.audit(
                    database,
                    "logout",
                    client_ip=context.client_ip,
                    user_agent=context.user_agent,
                    user_id=user["id"],
                    email=user["email"],
                )
            database.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))
    return ActionResult({"ok": True}, clear_session=True)


def auth_me(user: dict | None) -> ActionResult:
    if not user:
        raise ApiError("authentication_required", "Authentication required", HTTPStatus.UNAUTHORIZED)
    return ActionResult({"user": user})


def email_verification_request(user: dict, context: RequestContext) -> ActionResult:
    if user["emailVerified"]:
        raise ApiError("email_already_verified", "Email уже подтверждён", HTTPStatus.CONFLICT)
    _ensure_auth_attempt_allowed("email_verification", user["email"], context.client_ip)
    with connect() as database:
        token = issue_token(database, "email_verification", user["id"])
        account_services.audit(
            database,
            "email_verification_requested",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
        )
    delivery = account_services.send_account_link(
        connect,
        runtime.DATA_DIR,
        "email_verification",
        user["email"],
        token,
        public_url=account_public_url(),
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    return ActionResult({"ok": True, "delivery": delivery})


def email_verification_confirm(payload: TokenRequest, context: RequestContext) -> ActionResult:
    with connect() as database:
        user = consume_token(database, "email_verification", payload.token)
        if not user:
            raise ApiError("token_invalid", "Ссылка недействительна или устарела", HTTPStatus.BAD_REQUEST)
        verified_at = int(time.time())
        database.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (verified_at, user["id"]))
        account_services.audit(
            database,
            "email_verified",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
        )
    return ActionResult({"ok": True})


def password_reset_request(payload: EmailRequest, context: RequestContext) -> ActionResult:
    email = payload.email.strip().lower()
    _ensure_auth_attempt_allowed("password_reset", email, context.client_ip)
    with connect() as database:
        user = database.execute("SELECT id, email FROM users WHERE email = ?", (email,)).fetchone()
        if user:
            token = issue_token(database, "password_reset", user["id"])
            account_services.audit(
                database,
                "password_reset_requested",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                user_id=user["id"],
                email=email,
            )
        else:
            token = None
            account_services.audit(
                database,
                "password_reset_requested_unknown",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                email=email,
            )
    if token:
        account_services.send_account_link(
            connect,
            runtime.DATA_DIR,
            "password_reset",
            email,
            token,
            public_url=account_public_url(),
            client_ip=context.client_ip,
            user_agent=context.user_agent,
        )
    return ActionResult({"ok": True, "message": "Если аккаунт существует, инструкция отправлена"})


def password_reset_confirm(payload: PasswordResetRequest, context: RequestContext) -> ActionResult:
    password = payload.password
    if not 8 <= len(password) <= 128:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST),
            "Пароль должен содержать от 8 до 128 символов",
            HTTPStatus.BAD_REQUEST,
        )
    with connect() as database:
        user = consume_token(database, "password_reset", payload.token)
        if not user:
            raise ApiError("token_invalid", "Ссылка недействительна или устарела", HTTPStatus.BAD_REQUEST)
        database.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash(password), user["id"]))
        database.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        clear_rate_limit(database, "login", context.client_ip, user["email"])
        account_services.audit(
            database,
            "password_reset_completed",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
        )
    return ActionResult({"ok": True}, clear_session=True)


def account_audit(user: dict) -> ActionResult:
    with connect() as database:
        events = audit_events(database, user["id"])
    return ActionResult({"events": events})


def account_delete(payload: DeleteAccountRequest, user: dict, context: RequestContext) -> ActionResult:
    password = payload.password
    with connect() as database:
        row = database.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row or not password_matches(password, row["password_hash"]):
            account_services.audit(
                database,
                "account_deletion_failed",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                user_id=user["id"],
                email=user["email"],
            )
            raise ApiError("invalid_password", "Неверный пароль", HTTPStatus.UNAUTHORIZED)
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
        audio_keys = [item["file_name"] for item in files]
        material_keys = [item["storage_key"] for item in material_assets]
        assignment_keys = [item["storage_key"] for item in assignment_assets]
        account_services.audit(
            database,
            "account_deleted",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
        )
        database.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    # Файлы удаляем только после коммита: иначе откат транзакции оставил бы
    # живой аккаунт со строками, ссылающимися на уже уничтоженные файлы.
    try:
        delete_account_storage(
            runtime.AUDIO_DIR,
            audio_keys,
            runtime.MATERIAL_ASSET_DIR,
            material_keys,
            runtime.ASSIGNMENT_ASSET_DIR,
            assignment_keys,
        )
    except Exception:
        # Аккаунт уже удалён, поэтому запрос считается успешным, но остаток
        # файлов требует ручной уборки — пишем причину и объём в лог.
        logging.getLogger("trainer.accounts").exception(
            "Account storage cleanup failed",
            extra={
                "event": "account_storage_cleanup_failed",
                "fields": {
                    "userId": user["id"],
                    "audioKeys": len(audio_keys),
                    "materialKeys": len(material_keys),
                    "assignmentKeys": len(assignment_keys),
                },
            },
        )
    return ActionResult({"ok": True}, clear_session=True)
