from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager

from trainer.domain.accounts import token_digest
from trainer.infrastructure.database.accounts import (
    audit_events as read_audit_events,
)
from trainer.infrastructure.database.accounts import (
    clear_rate_limit,
    consume_rate_limit,
    consume_token,
    issue_token,
    record_audit,
)
from trainer.infrastructure.database.core import INTEGRITY_ERRORS
from trainer.infrastructure.database.storage_cleanup_repository import SQLiteStorageCleanupQueue
from trainer.services.account_repository import (
    AccountAuditEvent,
    AccountAuditRecord,
    AccountConflictError,
    AccountIdentity,
    AccountProfile,
    AccountRecord,
    AccountRepositorySession,
    AuthAttemptKind,
)
from trainer.services.storage_cleanup_repository import CleanupKeys


def _keys(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def _profile(row: sqlite3.Row) -> AccountProfile:
    return AccountProfile(
        row["id"],
        row["email"],
        row["display_name"],
        row["role"],
        row["email_verified_at"],
    )


def _record(row: sqlite3.Row) -> AccountRecord:
    return AccountRecord(
        row["id"],
        row["email"],
        row["display_name"],
        row["role"],
        row["email_verified_at"],
        row["password_hash"],
    )


class SQLiteAccountRepositorySession:
    def __init__(self, database: sqlite3.Connection):
        self.database = database

    def consume_rate_limit(
        self,
        kind: AuthAttemptKind,
        client_ip: str,
        email: str,
        now: int,
    ) -> int:
        return consume_rate_limit(self.database, kind, client_ip, email, now)

    def clear_rate_limit(
        self,
        kind: AuthAttemptKind,
        client_ip: str,
        email: str,
    ) -> None:
        clear_rate_limit(self.database, kind, client_ip, email)

    def user_by_email(self, email: str) -> AccountRecord | None:
        row = self.database.execute(
            """SELECT id,email,password_hash,display_name,role,email_verified_at
               FROM users WHERE email=?""",
            (email,),
        ).fetchone()
        return _record(row) if row else None

    def user_by_id(self, user_id: int) -> AccountRecord | None:
        row = self.database.execute(
            """SELECT id,email,password_hash,display_name,role,email_verified_at
               FROM users WHERE id=?""",
            (user_id,),
        ).fetchone()
        return _record(row) if row else None

    def session_identity(self, token: str) -> AccountIdentity | None:
        row = self.database.execute(
            """SELECT users.id,users.email FROM sessions
               JOIN users ON users.id=sessions.user_id
               WHERE sessions.token_hash=?""",
            (token_digest(token),),
        ).fetchone()
        return AccountIdentity(row["id"], row["email"]) if row else None

    def create_user(
        self,
        email: str,
        password_hash: str,
        display_name: str,
        role: str,
        created_at: int,
    ) -> int:
        try:
            return self.database.execute(
                """INSERT INTO users(email,password_hash,display_name,role,created_at)
                   VALUES (?,?,?,?,?)""",
                (email, password_hash, display_name, role, created_at),
            ).lastrowid
        except INTEGRITY_ERRORS as error:
            raise AccountConflictError from error

    def create_session(self, user_id: int, expires_at: int, created_at: int) -> str:
        token = secrets.token_urlsafe(32)
        self.database.execute(
            """INSERT INTO sessions(token_hash,user_id,expires_at,created_at)
               VALUES (?,?,?,?)""",
            (token_digest(token), user_id, expires_at, created_at),
        )
        return token

    def delete_session(self, token: str) -> None:
        self.database.execute(
            "DELETE FROM sessions WHERE token_hash=?",
            (token_digest(token),),
        )

    def issue_token(self, kind, user_id: int, now: int) -> str:
        return issue_token(self.database, kind, user_id, now)

    def consume_token(self, kind, token: str, now: int) -> AccountProfile | None:
        row = consume_token(self.database, kind, token, now)
        return _profile(row) if row else None

    def verify_email(self, user_id: int, verified_at: int) -> None:
        self.database.execute(
            "UPDATE users SET email_verified_at=? WHERE id=?",
            (verified_at, user_id),
        )

    def replace_password(self, user_id: int, password_hash: str) -> None:
        self.database.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (password_hash, user_id),
        )

    def delete_user_sessions(self, user_id: int) -> None:
        self.database.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def audit(self, event: AccountAuditEvent) -> None:
        record_audit(
            self.database,
            event.action,
            user_id=event.user_id,
            email=event.email,
            ip_address=event.metadata.client_ip,
            user_agent=event.metadata.user_agent,
            details=dict(event.details),
            now=event.created_at,
        )

    def enqueue_account_cleanup(self, user_id: int, now: int) -> None:
        legacy_recordings = self.database.execute(
            """SELECT recordings.file_name FROM recordings
               JOIN submissions ON submissions.id=recordings.submission_id
               JOIN assignments ON assignments.id=submissions.assignment_id
               WHERE submissions.student_id=? OR assignments.teacher_id=?""",
            (user_id, user_id),
        ).fetchall()
        material_assets = self.database.execute(
            """SELECT material_assets.storage_key FROM material_assets
               JOIN materials ON materials.id=material_assets.material_id
               WHERE materials.owner_id=?""",
            (user_id,),
        ).fetchall()
        assignment_assets = self.database.execute(
            """SELECT assignment_material_assets.storage_key FROM assignment_material_assets
               JOIN assignments ON assignments.id=assignment_material_assets.assignment_id
               WHERE assignments.teacher_id=?""",
            (user_id,),
        ).fetchall()
        review_recordings = self.database.execute(
            """SELECT review_request_recordings.storage_key
               FROM review_request_recordings
               JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
               JOIN review_requests ON review_requests.id=review_request_items.request_id
               WHERE review_requests.student_id=?""",
            (user_id,),
        ).fetchall()
        review_assets = self.database.execute(
            """SELECT review_request_assets.storage_key
               FROM review_request_assets
               JOIN review_requests ON review_requests.id=review_request_assets.request_id
               WHERE review_requests.student_id=?""",
            (user_id,),
        ).fetchall()
        personal_recordings = self.database.execute(
            "SELECT storage_key FROM personal_recordings WHERE student_id=?",
            (user_id,),
        ).fetchall()
        SQLiteStorageCleanupQueue(self.database).enqueue(
            CleanupKeys(
                audio=_keys(row["file_name"] for row in legacy_recordings)
                + _keys(row["storage_key"] for row in [*review_recordings, *personal_recordings]),
                material=_keys(row["storage_key"] for row in material_assets),
                assignment=_keys(row["storage_key"] for row in [*assignment_assets, *review_assets]),
            ),
            now=now,
        )

    def delete_user(self, user_id: int) -> None:
        self.database.execute("DELETE FROM users WHERE id=?", (user_id,))


class SQLiteAccountRepository:
    def __init__(self, connect_factory: Callable[[], sqlite3.Connection]):
        self._connect = connect_factory

    @contextmanager
    def transaction(self) -> Iterator[AccountRepositorySession]:
        database = self._connect()
        try:
            yield SQLiteAccountRepositorySession(database)
            database.commit()
        except Exception:
            database.rollback()
            raise
        finally:
            database.close()

    def current_user(self, token: str, now: int) -> AccountProfile | None:
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT users.id,users.email,users.display_name,users.role,users.email_verified_at
                   FROM sessions JOIN users ON users.id=sessions.user_id
                   WHERE sessions.token_hash=? AND sessions.expires_at>?""",
                (token_digest(token), now),
            ).fetchone()
        return _profile(row) if row else None

    def audit_events(self, user_id: int, limit: int = 50) -> list[AccountAuditRecord]:
        with closing(self._connect()) as database:
            events = read_audit_events(database, user_id, limit)
        return [
            AccountAuditRecord(
                event["action"],
                event["ipAddress"],
                event["userAgent"],
                event["details"],
                event["createdAt"],
            )
            for event in events
        ]
