from __future__ import annotations

import unittest
from contextlib import contextmanager

from trainer.domain.accounts import password_hash
from trainer.services.account_repository import (
    AccountAuditEvent,
    AccountAuditRecord,
    AccountConflictError,
    AccountIdentity,
    AccountProfile,
    AccountRecord,
    AccountRequestMetadata,
)
from trainer.services.accounts import AccountError, AccountService


class FakeAccountRepositorySession:
    def __init__(self, repository: FakeAccountRepository, operations: list[str]):
        self.repository = repository
        self.operations = operations

    def _record(self, operation: str) -> None:
        self.operations.append(operation)

    def consume_rate_limit(self, kind, client_ip, email, now):
        self._record(f"consume_rate_limit:{kind}")
        self.repository.rate_limit_calls.append((kind, client_ip, email, now))
        return self.repository.retry_after

    def clear_rate_limit(self, kind, client_ip, email):
        self._record(f"clear_rate_limit:{kind}")
        self.repository.cleared_limits.append((kind, client_ip, email))

    def user_by_email(self, email):
        self._record("user_by_email")
        return next((user for user in self.repository.users.values() if user.email == email), None)

    def user_by_id(self, user_id):
        self._record("user_by_id")
        return self.repository.users.get(user_id)

    def session_identity(self, token):
        self._record("session_identity")
        session = self.repository.sessions.get(token)
        user = self.repository.users.get(session[0]) if session else None
        return AccountIdentity(user.id, user.email) if user else None

    def create_user(self, email, encoded_password, display_name, role, created_at):
        self._record("create_user")
        if any(user.email == email for user in self.repository.users.values()):
            raise AccountConflictError
        user_id = self.repository.next_user_id
        self.repository.next_user_id += 1
        self.repository.users[user_id] = AccountRecord(
            user_id,
            email,
            display_name,
            role,
            None,
            encoded_password,
        )
        return user_id

    def create_session(self, user_id, expires_at, created_at):
        self._record("create_session")
        token = f"session-{self.repository.next_session_id}"
        self.repository.next_session_id += 1
        self.repository.sessions[token] = (user_id, expires_at, created_at)
        return token

    def delete_session(self, token):
        self._record("delete_session")
        self.repository.sessions.pop(token, None)

    def issue_token(self, kind, user_id, now):
        self._record(f"issue_token:{kind}")
        token = f"{kind}-{user_id}-{self.repository.next_account_token_id}"
        self.repository.next_account_token_id += 1
        self.repository.tokens[token] = (kind, user_id, now)
        return token

    def consume_token(self, kind, token, now):
        self._record(f"consume_token:{kind}")
        stored = self.repository.tokens.pop(token, None)
        if not stored or stored[0] != kind:
            return None
        user = self.repository.users.get(stored[1])
        if not user:
            return None
        return AccountProfile(user.id, user.email, user.display_name, user.role, user.email_verified_at)

    def verify_email(self, user_id, verified_at):
        self._record("verify_email")
        user = self.repository.users[user_id]
        self.repository.users[user_id] = AccountRecord(
            user.id,
            user.email,
            user.display_name,
            user.role,
            verified_at,
            user.password_hash,
        )

    def replace_password(self, user_id, encoded_password):
        self._record("replace_password")
        user = self.repository.users[user_id]
        self.repository.users[user_id] = AccountRecord(
            user.id,
            user.email,
            user.display_name,
            user.role,
            user.email_verified_at,
            encoded_password,
        )

    def delete_user_sessions(self, user_id):
        self._record("delete_user_sessions")
        self.repository.sessions = {
            token: session for token, session in self.repository.sessions.items() if session[0] != user_id
        }

    def audit(self, event: AccountAuditEvent):
        self._record(f"audit:{event.action}")
        self.repository.written_audits.append(event)

    def enqueue_account_cleanup(self, user_id, now):
        self._record("enqueue_account_cleanup")
        self.repository.cleanup_enqueues.append((user_id, now))

    def delete_user(self, user_id):
        self._record("delete_user")
        self.repository.users.pop(user_id, None)
        self.delete_user_sessions(user_id)


class FakeAccountRepository:
    def __init__(self):
        self.users: dict[int, AccountRecord] = {}
        self.sessions: dict[str, tuple[int, int, int]] = {}
        self.tokens: dict[str, tuple[str, int, int]] = {}
        self.written_audits: list[AccountAuditEvent] = []
        self.read_audit_events: list[AccountAuditRecord] = []
        self.transactions: list[list[str]] = []
        self.rate_limit_calls: list[tuple[str, str, str, int]] = []
        self.cleared_limits: list[tuple[str, str, str]] = []
        self.cleanup_enqueues: list[tuple[int, int]] = []
        self.audit_limits: list[tuple[int, int]] = []
        self.retry_after = 0
        self.next_user_id = 1
        self.next_session_id = 1
        self.next_account_token_id = 1

    @contextmanager
    def transaction(self):
        operations: list[str] = []
        self.transactions.append(operations)
        yield FakeAccountRepositorySession(self, operations)

    def current_user(self, token, now):
        session = self.sessions.get(token)
        if not session or session[1] <= now:
            return None
        user = self.users.get(session[0])
        if not user:
            return None
        return AccountProfile(user.id, user.email, user.display_name, user.role, user.email_verified_at)

    def audit_events(self, user_id, limit=50):
        self.audit_limits.append((user_id, limit))
        return self.read_audit_events[:limit]

    def add_user(
        self,
        email: str,
        password: str,
        *,
        display_name: str = "User",
        role: str = "student",
        email_verified_at: int | None = None,
    ) -> int:
        user_id = self.next_user_id
        self.next_user_id += 1
        self.users[user_id] = AccountRecord(
            user_id,
            email,
            display_name,
            role,
            email_verified_at,
            password_hash(password),
        )
        return user_id

    def audit_actions(self) -> list[str]:
        return [event.action for event in self.written_audits]


class FakeLinkSender:
    def __init__(self):
        self.messages: list[tuple[str, str, str]] = []
        self.error: Exception | None = None

    def send(self, kind, email, token):
        self.messages.append((kind, email, token))
        if self.error:
            raise self.error
        return "outbox"


class FakeCleanupRunner:
    def __init__(self):
        self.calls = 0
        self.error: Exception | None = None

    def __call__(self):
        self.calls += 1
        if self.error:
            raise self.error
        from trainer.services.account_repository import AccountCleanupSummary

        return AccountCleanupSummary(completed=1)


class AccountServiceCoreTest(unittest.TestCase):
    def setUp(self):
        self.repository = FakeAccountRepository()
        self.sender = FakeLinkSender()
        self.cleanup = FakeCleanupRunner()
        self.service = AccountService(
            self.repository,
            self.sender,
            self.cleanup,
            owner_email="owner@example.test",
            session_days=30,
            clock=lambda: 1_700_000_000,
        )
        self.metadata = AccountRequestMetadata("127.0.0.1", "unit-test")

    def test_register_normalizes_owner_creates_token_session_audit_and_clears_limit(self):
        result = self.service.register(" Owner@Example.Test ", "password123", "  Владелец  ", self.metadata)

        self.assertEqual(
            result.user,
            {
                "id": 1,
                "email": "owner@example.test",
                "displayName": "Владелец",
                "role": "teacher",
                "emailVerified": False,
            },
        )
        self.assertEqual(result.session_token, "session-1")
        self.assertEqual(result.verification_delivery, "outbox")
        self.assertEqual(
            self.sender.messages,
            [("email_verification", "owner@example.test", "email_verification-1-1")],
        )
        self.assertEqual(self.repository.audit_actions(), ["account_registered"])
        self.assertEqual(
            self.repository.cleared_limits,
            [("register", "127.0.0.1", "owner@example.test")],
        )
        self.assertEqual(self.repository.sessions["session-1"][1], 1_700_000_000 + 30 * 86400)

    def test_register_consumes_limit_before_reporting_invalid_credentials(self):
        with self.assertRaises(AccountError) as raised:
            self.service.register("invalid", "password123", "Ученик", self.metadata)

        self.assertEqual(raised.exception.reason, "invalid_input")
        self.assertEqual(raised.exception.message, "Введите корректный email")
        self.assertEqual(self.repository.rate_limit_calls[0][0], "register")
        self.assertEqual(self.repository.users, {})

    def test_register_rejects_display_name_outside_bounds(self):
        for display_name in ("A", "A" * 81):
            with self.subTest(length=len(display_name)):
                with self.assertRaises(AccountError) as raised:
                    self.service.register("user@example.test", "password123", display_name, self.metadata)
                self.assertEqual(raised.exception.reason, "invalid_input")
                self.assertEqual(raised.exception.message, "Укажите имя длиной от 2 до 80 символов")

    def test_register_translates_duplicate_email_conflict(self):
        self.repository.add_user("user@example.test", "password123")

        with self.assertRaises(AccountError) as raised:
            self.service.register("user@example.test", "password123", "Ученик", self.metadata)

        self.assertEqual(raised.exception.reason, "email_already_registered")
        self.assertEqual(raised.exception.message, "Аккаунт с таким email уже существует")

    def test_rate_limit_error_carries_retry_after(self):
        self.repository.retry_after = 37

        with self.assertRaises(AccountError) as raised:
            self.service.login("user@example.test", "password123", self.metadata)

        self.assertEqual(raised.exception.reason, "rate_limited")
        self.assertEqual(raised.exception.retry_after, 37)

    def test_login_failure_audits_without_creating_session(self):
        self.repository.add_user("user@example.test", "password123")

        with self.assertRaises(AccountError) as raised:
            self.service.login("USER@example.test", "wrong-password", self.metadata)

        self.assertEqual(raised.exception.reason, "invalid_credentials")
        self.assertEqual(raised.exception.message, "Неверный email или пароль")
        self.assertEqual(self.repository.audit_actions(), ["login_failed"])
        self.assertEqual(self.repository.sessions, {})

    def test_login_success_creates_session_then_clears_limit_and_audits(self):
        self.repository.add_user("user@example.test", "password123")

        result = self.service.login(" USER@example.test ", "password123", self.metadata)

        self.assertEqual(result.session_token, "session-1")
        self.assertEqual(result.user["email"], "user@example.test")
        self.assertEqual(self.repository.audit_actions(), ["login_succeeded"])
        self.assertEqual(
            self.repository.cleared_limits,
            [("login", "127.0.0.1", "user@example.test")],
        )

    def test_current_user_hides_password_hash_and_rejects_missing_or_expired_token(self):
        self.assertIsNone(self.service.current_user(None))
        user_id = self.repository.add_user("user@example.test", "password123")
        self.repository.sessions["valid"] = (user_id, 1_700_000_001, 1_699_999_999)
        self.repository.sessions["expired"] = (user_id, 1_700_000_000, 1_699_999_999)

        self.assertEqual(
            self.service.current_user("valid"),
            {
                "id": user_id,
                "email": "user@example.test",
                "displayName": "User",
                "role": "student",
                "emailVerified": False,
            },
        )
        self.assertIsNone(self.service.current_user("expired"))

    def test_logout_is_idempotent_and_audits_only_a_resolved_session(self):
        self.service.logout(None, self.metadata)
        self.service.logout("unknown", self.metadata)
        self.assertEqual(self.repository.audit_actions(), [])

        user_id = self.repository.add_user("user@example.test", "password123")
        self.repository.sessions["valid"] = (user_id, 1_700_000_001, 1_699_999_999)
        self.service.logout("valid", self.metadata)

        self.assertEqual(self.repository.audit_actions(), ["logout"])
        self.assertNotIn("valid", self.repository.sessions)


if __name__ == "__main__":
    unittest.main()
