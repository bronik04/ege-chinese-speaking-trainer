from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from trainer.domain.accounts import (
    password_hash,
    password_matches,
    registration_role,
    token_digest,
    validate_credentials,
)
from trainer.infrastructure.database.accounts import record_audit
from trainer.infrastructure.mailer import send_email
from trainer.infrastructure.storage import storage_from_env
from trainer.services.account_repository import (
    AccountAuditEvent,
    AccountCleanupRunner,
    AccountConflictError,
    AccountLinkKind,
    AccountLinkSender,
    AccountProfile,
    AccountRepository,
    AccountRequestMetadata,
    AuthAttemptKind,
)

logger = logging.getLogger("trainer.accounts")


def user_payload(user_id: int, email: str, display_name: str, role: str, email_verified_at: int | None) -> dict:
    return {
        "id": user_id,
        "email": email,
        "displayName": display_name,
        "role": role,
        "emailVerified": email_verified_at is not None,
    }


@dataclass(frozen=True)
class RegistrationResult:
    user: dict
    session_token: str
    verification_delivery: str


@dataclass(frozen=True)
class LoginResult:
    user: dict
    session_token: str


class AccountError(Exception):
    def __init__(self, reason: str, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.retry_after = retry_after


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        link_sender: AccountLinkSender,
        cleanup_runner: AccountCleanupRunner,
        *,
        owner_email: str,
        session_days: int = 30,
        clock: Callable[[], float] = time.time,
    ):
        self._repository = repository
        self._link_sender = link_sender
        self._cleanup_runner = cleanup_runner
        self._owner_email = owner_email.strip().lower()
        self._session_days = session_days
        self._clock = clock

    def _now(self) -> int:
        return int(self._clock())

    @staticmethod
    def _public_user(user: AccountProfile) -> dict:
        return user_payload(
            user.id,
            user.email,
            user.display_name,
            user.role,
            user.email_verified_at,
        )

    @staticmethod
    def _audit_event(
        action: str,
        metadata: AccountRequestMetadata,
        now: int,
        *,
        user_id: int | None = None,
        email: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> AccountAuditEvent:
        return AccountAuditEvent(
            action,
            metadata,
            now,
            user_id=user_id,
            email=email,
            details=details or {},
        )

    def _consume_attempt(
        self,
        kind: AuthAttemptKind,
        email: str,
        metadata: AccountRequestMetadata,
        now: int,
    ) -> None:
        with self._repository.transaction() as transaction:
            retry_after = transaction.consume_rate_limit(kind, metadata.client_ip, email, now)
        if retry_after:
            raise AccountError(
                "rate_limited",
                "Слишком много попыток. Попробуйте позже",
                retry_after=retry_after,
            )

    def _deliver(
        self,
        kind: AccountLinkKind,
        user_id: int,
        email: str,
        token: str,
        metadata: AccountRequestMetadata,
    ) -> str:
        try:
            return self._link_sender.send(kind, email, token)
        except Exception as error:
            now = self._now()
            with self._repository.transaction() as transaction:
                transaction.audit(
                    self._audit_event(
                        "email_delivery_failed",
                        metadata,
                        now,
                        user_id=user_id,
                        email=email,
                        details={"kind": kind},
                    )
                )
            logger.warning(
                "Account email delivery failed",
                extra={
                    "event": "account_email_delivery_failed",
                    "fields": {"kind": kind, "error": type(error).__name__},
                },
            )
            return "failed"

    def register(
        self,
        raw_email: str,
        raw_password: str,
        raw_display_name: str,
        metadata: AccountRequestMetadata,
    ) -> RegistrationResult:
        email, password, validation_error = validate_credentials(raw_email, raw_password)
        now = self._now()
        self._consume_attempt("register", email, metadata, now)
        if validation_error:
            raise AccountError("invalid_input", validation_error)
        display_name = raw_display_name.strip()
        if not 2 <= len(display_name) <= 80:
            raise AccountError("invalid_input", "Укажите имя длиной от 2 до 80 символов")
        role = registration_role(email, self._owner_email)
        try:
            with self._repository.transaction() as transaction:
                user_id = transaction.create_user(
                    email,
                    password_hash(password),
                    display_name,
                    role,
                    now,
                )
                verification_token = transaction.issue_token("email_verification", user_id, now)
                transaction.audit(
                    self._audit_event(
                        "account_registered",
                        metadata,
                        now,
                        user_id=user_id,
                        email=email,
                        details={"role": role},
                    )
                )
        except AccountConflictError as error:
            raise AccountError(
                "email_already_registered",
                "Аккаунт с таким email уже существует",
            ) from error
        with self._repository.transaction() as transaction:
            session_token = transaction.create_session(
                user_id,
                now + self._session_days * 86400,
                now,
            )
        with self._repository.transaction() as transaction:
            transaction.clear_rate_limit("register", metadata.client_ip, email)
        delivery = self._deliver(
            "email_verification",
            user_id,
            email,
            verification_token,
            metadata,
        )
        return RegistrationResult(
            user_payload(user_id, email, display_name, role, None),
            session_token,
            delivery,
        )

    def login(
        self,
        raw_email: str,
        password: str,
        metadata: AccountRequestMetadata,
    ) -> LoginResult:
        email = raw_email.strip().lower()
        now = self._now()
        self._consume_attempt("login", email, metadata, now)
        with self._repository.transaction() as transaction:
            user = transaction.user_by_email(email)
        if not user or not password_matches(password, user.password_hash):
            with self._repository.transaction() as transaction:
                transaction.audit(
                    self._audit_event(
                        "login_failed",
                        metadata,
                        now,
                        user_id=user.id if user else None,
                        email=email,
                    )
                )
            raise AccountError("invalid_credentials", "Неверный email или пароль")
        with self._repository.transaction() as transaction:
            session_token = transaction.create_session(
                user.id,
                now + self._session_days * 86400,
                now,
            )
        with self._repository.transaction() as transaction:
            transaction.clear_rate_limit("login", metadata.client_ip, email)
            transaction.audit(
                self._audit_event(
                    "login_succeeded",
                    metadata,
                    now,
                    user_id=user.id,
                    email=email,
                )
            )
        return LoginResult(self._public_user(user), session_token)

    def current_user(self, token: str | None) -> dict | None:
        if not token:
            return None
        user = self._repository.current_user(token, self._now())
        return self._public_user(user) if user else None

    def logout(self, token: str | None, metadata: AccountRequestMetadata) -> None:
        if not token:
            return
        now = self._now()
        with self._repository.transaction() as transaction:
            identity = transaction.session_identity(token)
            if identity:
                transaction.audit(
                    self._audit_event(
                        "logout",
                        metadata,
                        now,
                        user_id=identity.id,
                        email=identity.email,
                    )
                )
            transaction.delete_session(token)

    def request_email_verification(
        self,
        user_id: int,
        email: str,
        email_verified: bool,
        metadata: AccountRequestMetadata,
    ) -> str:
        if email_verified:
            raise AccountError("email_already_verified", "Email уже подтверждён")
        normalized_email = email.strip().lower()
        now = self._now()
        self._consume_attempt("email_verification", normalized_email, metadata, now)
        with self._repository.transaction() as transaction:
            token = transaction.issue_token("email_verification", user_id, now)
            transaction.audit(
                self._audit_event(
                    "email_verification_requested",
                    metadata,
                    now,
                    user_id=user_id,
                    email=normalized_email,
                )
            )
        return self._deliver(
            "email_verification",
            user_id,
            normalized_email,
            token,
            metadata,
        )

    def confirm_email_verification(
        self,
        token: str,
        metadata: AccountRequestMetadata,
    ) -> None:
        now = self._now()
        with self._repository.transaction() as transaction:
            user = transaction.consume_token("email_verification", token, now)
            if not user:
                raise AccountError("token_invalid", "Ссылка недействительна или устарела")
            transaction.verify_email(user.id, now)
            transaction.audit(
                self._audit_event(
                    "email_verified",
                    metadata,
                    now,
                    user_id=user.id,
                    email=user.email,
                )
            )

    def request_password_reset(
        self,
        raw_email: str,
        metadata: AccountRequestMetadata,
    ) -> None:
        email = raw_email.strip().lower()
        now = self._now()
        self._consume_attempt("password_reset", email, metadata, now)
        with self._repository.transaction() as transaction:
            user = transaction.user_by_email(email)
            if user:
                token = transaction.issue_token("password_reset", user.id, now)
                transaction.audit(
                    self._audit_event(
                        "password_reset_requested",
                        metadata,
                        now,
                        user_id=user.id,
                        email=email,
                    )
                )
            else:
                token = None
                transaction.audit(
                    self._audit_event(
                        "password_reset_requested_unknown",
                        metadata,
                        now,
                        email=email,
                    )
                )
        if user and token:
            self._deliver("password_reset", user.id, email, token, metadata)

    def confirm_password_reset(
        self,
        token: str,
        password: str,
        metadata: AccountRequestMetadata,
    ) -> None:
        if not 8 <= len(password) <= 128:
            raise AccountError("invalid_input", "Пароль должен содержать от 8 до 128 символов")
        now = self._now()
        with self._repository.transaction() as transaction:
            user = transaction.consume_token("password_reset", token, now)
            if not user:
                raise AccountError("token_invalid", "Ссылка недействительна или устарела")
            transaction.replace_password(user.id, password_hash(password))
            transaction.delete_user_sessions(user.id)
            transaction.clear_rate_limit("login", metadata.client_ip, user.email)
            transaction.audit(
                self._audit_event(
                    "password_reset_completed",
                    metadata,
                    now,
                    user_id=user.id,
                    email=user.email,
                )
            )

    def audit_events(self, user_id: int) -> list[dict]:
        return [
            {
                "action": event.action,
                "ipAddress": event.ip_address,
                "userAgent": event.user_agent,
                "details": dict(event.details),
                "createdAt": event.created_at,
            }
            for event in self._repository.audit_events(user_id, 50)
        ]

    def delete_account(
        self,
        user_id: int,
        email: str,
        password: str,
        metadata: AccountRequestMetadata,
    ) -> None:
        now = self._now()
        invalid_password = False
        with self._repository.transaction() as transaction:
            user = transaction.user_by_id(user_id)
            if not user or not password_matches(password, user.password_hash):
                transaction.audit(
                    self._audit_event(
                        "account_deletion_failed",
                        metadata,
                        now,
                        user_id=user_id,
                        email=email,
                    )
                )
                invalid_password = True
            else:
                transaction.enqueue_account_cleanup(user_id, now)
                transaction.audit(
                    self._audit_event(
                        "account_deleted",
                        metadata,
                        now,
                        user_id=user_id,
                        email=email,
                    )
                )
                transaction.delete_user(user_id)
        if invalid_password:
            raise AccountError("invalid_password", "Неверный пароль")
        try:
            summary = self._cleanup_runner()
            logger.info(
                "Account storage cleanup processed",
                extra={
                    "event": "account_storage_cleanup_processed",
                    "fields": {
                        "completed": summary.completed,
                        "failed": summary.failed,
                        "pending": summary.pending,
                    },
                },
            )
        except Exception:
            logger.error(
                "Account storage cleanup failed",
                extra={
                    "event": "account_storage_cleanup_failed",
                    "fields": {"userId": user_id},
                },
            )


def create_session(connect_factory, user_id: int, session_days: int, now: int | None = None) -> str:
    token = secrets.token_urlsafe(32)
    moment = int(time.time()) if now is None else int(now)
    with connect_factory() as database:
        database.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token_digest(token), user_id, moment + session_days * 86400, moment),
        )
    return token


def current_user(connect_factory, token: str | None, now: int | None = None) -> dict | None:
    if not token:
        return None
    moment = int(time.time()) if now is None else int(now)
    with connect_factory() as database:
        row = database.execute(
            """
            SELECT users.id, users.email, users.display_name, users.role, users.email_verified_at FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (token_digest(token), moment),
        ).fetchone()
    return (
        user_payload(row["id"], row["email"], row["display_name"], row["role"], row["email_verified_at"])
        if row
        else None
    )


def user_for_token(database, token: str):
    return database.execute(
        """
        SELECT users.id, users.email FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token_hash = ?
        """,
        (token_digest(token),),
    ).fetchone()


def audit(database, action: str, *, client_ip: str, user_agent: str, **fields) -> None:
    record_audit(database, action, ip_address=client_ip, user_agent=user_agent, **fields)


def send_account_link(
    connect_factory,
    data_dir: Path,
    kind: str,
    email: str,
    token: str,
    *,
    public_url: str,
    client_ip: str,
    user_agent: str,
) -> str:
    parameter = "verify" if kind == "email_verification" else "reset"
    url = f"{public_url.rstrip('/')}/?{parameter}={quote(token)}"
    if kind == "email_verification":
        subject = "Подтвердите email — тренажёр ЕГЭ"
        body = f"Подтвердите адрес электронной почты. Ссылка действует 24 часа:\n\n{url}"
    else:
        subject = "Восстановление пароля — тренажёр ЕГЭ"
        body = f"Создайте новый пароль. Ссылка действует 1 час:\n\n{url}"
    try:
        return send_email(data_dir, email, subject, body)
    except Exception as error:
        with connect_factory() as database:
            user = database.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            audit(
                database,
                "email_delivery_failed",
                client_ip=client_ip,
                user_agent=user_agent,
                user_id=user["id"] if user else None,
                email=email,
                details={"kind": kind},
            )
        print(f"Email delivery failed: {type(error).__name__}")
        return "failed"


def delete_account_storage(
    audio_root: Path,
    audio_keys,
    material_root: Path,
    material_keys,
    assignment_root: Path,
    assignment_keys,
) -> None:
    failure: Exception | None = None
    for root, keys in (
        (audio_root, audio_keys),
        (material_root, material_keys),
        (assignment_root, assignment_keys),
    ):
        try:
            storage = storage_from_env(root)
        except Exception as error:
            failure = failure or error
            continue
        for key in keys:
            try:
                storage.delete(key)
            except Exception as error:
                # Один недоступный ключ не должен оставлять остальные файлы
                # пользователя на диске: удаляем всё, что можем, и сообщаем
                # о первом отказе вызывающему коду.
                failure = failure or error
    if failure is not None:
        raise failure
