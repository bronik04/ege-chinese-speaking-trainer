from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Literal, Protocol

AuthAttemptKind = Literal["login", "register", "password_reset", "email_verification"]
AccountLinkKind = Literal["email_verification", "password_reset"]


@dataclass(frozen=True)
class AccountProfile:
    id: int
    email: str
    display_name: str
    role: str
    email_verified_at: int | None


@dataclass(frozen=True)
class AccountRecord(AccountProfile):
    password_hash: str


@dataclass(frozen=True)
class AccountIdentity:
    id: int
    email: str


@dataclass(frozen=True)
class AccountRequestMetadata:
    client_ip: str
    user_agent: str


@dataclass(frozen=True)
class AccountAuditEvent:
    action: str
    metadata: AccountRequestMetadata
    created_at: int
    user_id: int | None = None
    email: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountAuditRecord:
    action: str
    ip_address: str
    user_agent: str
    details: Mapping[str, object]
    created_at: int


@dataclass(frozen=True)
class AccountCleanupSummary:
    completed: int = 0
    failed: int = 0
    pending: int = 0


class AccountConflictError(Exception):
    pass


class AccountRepositorySession(Protocol):
    def consume_rate_limit(self, kind: AuthAttemptKind, client_ip: str, email: str, now: int) -> int: ...

    def clear_rate_limit(self, kind: AuthAttemptKind, client_ip: str, email: str) -> None: ...

    def user_by_email(self, email: str) -> AccountRecord | None: ...

    def user_by_id(self, user_id: int) -> AccountRecord | None: ...

    def session_identity(self, token: str) -> AccountIdentity | None: ...

    def create_user(
        self,
        email: str,
        password_hash: str,
        display_name: str,
        role: str,
        created_at: int,
    ) -> int: ...

    def create_session(self, user_id: int, expires_at: int, created_at: int) -> str: ...

    def delete_session(self, token: str) -> None: ...

    def issue_token(self, kind: AccountLinkKind, user_id: int, now: int) -> str: ...

    def consume_token(self, kind: AccountLinkKind, token: str, now: int) -> AccountProfile | None: ...

    def verify_email(self, user_id: int, verified_at: int) -> None: ...

    def replace_password(self, user_id: int, password_hash: str) -> None: ...

    def delete_user_sessions(self, user_id: int) -> None: ...

    def audit(self, event: AccountAuditEvent) -> None: ...

    def enqueue_account_cleanup(self, user_id: int, now: int) -> None: ...

    def delete_user(self, user_id: int) -> None: ...


class AccountRepository(Protocol):
    def transaction(self) -> AbstractContextManager[AccountRepositorySession]: ...

    def current_user(self, token: str, now: int) -> AccountProfile | None: ...

    def audit_events(self, user_id: int, limit: int = 50) -> list[AccountAuditRecord]: ...


class AccountLinkSender(Protocol):
    def send(self, kind: AccountLinkKind, email: str, token: str) -> str: ...


class AccountCleanupRunner(Protocol):
    def __call__(self) -> AccountCleanupSummary: ...
