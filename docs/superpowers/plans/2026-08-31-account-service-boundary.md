# Account Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SQL, mail, token, session, and storage-cleanup orchestration in the auth controller with a transport-independent `AccountService` backed by explicit ports and SQLite/mail adapters.

**Architecture:** Account routes and dependencies call a thin auth controller, which delegates all account use cases to `AccountService`. The service depends on `AccountRepository`, `AccountLinkSender`, and cleanup-runner ports; `SQLiteAccountRepository`, `MailAccountLinkSender`, and runtime composition provide the concrete infrastructure while preserving current HTTP contracts and transaction ordering.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, SQLite, `unittest`, dataclasses, typing `Protocol`, existing SMTP/outbox and durable storage-cleanup services.

**Spec:** `docs/superpowers/specs/2026-08-31-account-service-boundary-design.md`

## Global Constraints

- Keep all ten account routes, controller function signatures, Pydantic schemas, JSON fields, HTTP statuses, cookies, public error codes/messages/details, and audit action names unchanged.
- Keep the 30-day session, 24-hour email-verification token, 1-hour password-reset token, current token entropy, password hashing policy, and rate-limit thresholds/windows unchanged.
- Keep registration, login, token, audit, account-deletion, and post-commit cleanup commit points in the order documented by the spec.
- The only intentional observable correction is that `account_deletion_failed` must commit before returning `invalid_password`; the current controller accidentally rolls it back.
- Account deletion must enqueue every legacy recording, material, assignment, review, and personal-recording key before deleting the user, then attempt physical cleanup only after commit.
- `AccountService` and its ports must not import `trainer.api`, `trainer.infrastructure`, or `sqlite3`; adapters must not import `trainer.api`.
- Do not change database schema, migrations, frontend, content, routes, or Pydantic schemas.
- Follow test-driven development: observe each new test fail before adding the production behavior that makes it pass.
- Run `make check` before declaring completion; UI is unchanged, so `make test-e2e` is not required.

## File map

**Create**

- `src/trainer/services/account_repository.py` — adapter-neutral records, errors, repository/session, link-sender, and cleanup-runner ports.
- `src/trainer/infrastructure/database/account_repository.py` — SQLite implementation, row mapping, tokens, sessions, rate limits, audit, and account cleanup enqueue.
- `src/trainer/infrastructure/mailer/account_links.py` — verification/reset link composition over the existing mailer.
- `tests/unit/test_account_application_service.py` — application use cases against stateful fakes.
- `tests/unit/test_auth_controller.py` — transport result and semantic error mapping contracts.
- `tests/unit/test_account_link_sender.py` — exact link, subject, body, and delivery delegation.
- `tests/integration/test_account_repository.py` — SQLite transaction, TTL, audit, and deletion behavior.

**Modify**

- `src/trainer/services/accounts.py` — add `AccountService`, then remove infrastructure-coupled legacy helpers at API cutover.
- `src/trainer/infrastructure/database/accounts.py` — retain reusable SQLite primitives and constants; no API/service dependency.
- `src/trainer/infrastructure/database/material_repository.py` — write audit through `record_audit`, not concrete account service.
- `src/trainer/infrastructure/database/review_request_repository.py` — write audit through `record_audit`, not concrete account service.
- `src/trainer/config.py` — centralize owner email and public URL reads.
- `src/trainer/api/runtime.py` — compose account repository, mail sender, service, and cleanup runner.
- `src/trainer/api/controllers/auth.py` — reduce to service calls, API error mapping, and `ActionResult` creation.
- `src/trainer/api/dependencies.py` — resolve current user through runtime service and use centralized config.
- `tests/unit/test_account_links.py` — verify the centralized configuration helpers.
- `tests/unit/test_application_services.py` — remove the dead direct account-storage cleanup test.
- `tests/unit/test_architecture_boundaries.py` — enforce the new account dependency direction.
- `tests/integration/test_accounts.py` — exercise repository/service seams and runtime cleanup patching.
- `tests/integration/test_api_flows.py` — move cleanup patches from controller globals to runtime composition.
- `docs/architecture.md` — document the account vertical boundary and deletion transaction.

---

### Task 1: Define account ports and remove audit's reverse dependency

**Files:**

- Create: `src/trainer/services/account_repository.py`
- Modify: `src/trainer/infrastructure/database/material_repository.py`
- Modify: `src/trainer/infrastructure/database/review_request_repository.py`
- Modify: `tests/unit/test_architecture_boundaries.py`

**Interfaces:**

- Consumes: existing `record_audit(database, action, ...)` in `trainer.infrastructure.database.accounts`.
- Produces: `AccountProfile`, `AccountRecord`, `AccountIdentity`, `AccountRequestMetadata`, `AccountAuditEvent`, `AccountAuditRecord`, `AccountCleanupSummary`, `AccountConflictError`, `AccountRepository`, `AccountRepositorySession`, `AccountLinkSender`, and `AccountCleanupRunner`.

- [ ] **Step 1: Write the failing architecture tests**

Add tests that require the new port file to exist and prohibit infrastructure imports in it. Also require the two existing SQLite adapters to stop importing `trainer.services.accounts`:

```python
def test_account_port_has_no_adapter_dependencies(self):
    path = PACKAGE / "services" / "account_repository.py"
    self.assertTrue(path.is_file())
    imports = file_imports(path)
    self.assertNotIn("sqlite3", imports)
    self.assertFalse(any(module.startswith("trainer.api") for module in imports), imports)
    self.assertFalse(any(module.startswith("trainer.infrastructure") for module in imports), imports)

def test_database_adapters_do_not_import_concrete_account_service(self):
    for name in ("material_repository.py", "review_request_repository.py"):
        with self.subTest(name=name):
            imports = file_imports(PACKAGE / "infrastructure" / "database" / name)
            self.assertNotIn("trainer.services.accounts", imports)
```

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_architecture_boundaries.ArchitectureBoundaryTest.test_account_port_has_no_adapter_dependencies tests.unit.test_architecture_boundaries.ArchitectureBoundaryTest.test_database_adapters_do_not_import_concrete_account_service -v
```

Expected: the first test fails because `account_repository.py` does not exist; the second reports both concrete service imports.

- [ ] **Step 3: Create the exact port surface**

Create adapter-neutral types with these fields and signatures:

```python
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
        self, email: str, password_hash: str, display_name: str, role: str, created_at: int
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
```

Remove `from trainer.services import accounts as account_services` from both existing adapters. Import
`record_audit` and replace each `account_services.audit(...)` with:

```python
record_audit(
    self.database,
    event.action,
    ip_address=event.metadata.client_ip,
    user_agent=event.metadata.user_agent,
    user_id=event.actor.id,
    email=event.actor.email,
    details=dict(event.details),
)
```

Use the review adapter's existing argument names (`action`, `actor`, `metadata`, `details`) in its equivalent call.

- [ ] **Step 4: Run focused and affected tests**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_architecture_boundaries tests.unit.test_material_service tests.unit.test_review_request_service tests.integration.test_material_repository tests.integration.test_review_request_repository -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/trainer/services/account_repository.py src/trainer/infrastructure/database/material_repository.py src/trainer/infrastructure/database/review_request_repository.py tests/unit/test_architecture_boundaries.py
git commit -m "refactor: define account service ports"
```

---

### Task 2: Implement registration, login, session lookup, and logout in AccountService

**Files:**

- Create: `tests/unit/test_account_application_service.py`
- Modify: `src/trainer/services/accounts.py`

**Interfaces:**

- Consumes: all Task 1 account port types and existing pure functions `validate_credentials`, `registration_role`, `password_hash`, and `password_matches`.
- Produces: `AccountService.register()`, `login()`, `current_user()`, `logout()`, `RegistrationResult`, `LoginResult`, and `AccountError`.

- [ ] **Step 1: Build a stateful fake repository and write failing core-use-case tests**

The fake must implement the exact Task 1 Protocol, expose `transactions: list[list[str]]`, store users/sessions/audit events in memory, and allow deterministic tokens. Add tests with these assertions:

```python
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
        self.assertEqual(result.user["role"], "teacher")
        self.assertEqual(result.user["email"], "owner@example.test")
        self.assertEqual(result.user["displayName"], "Владелец")
        self.assertFalse(result.user["emailVerified"])
        self.assertEqual(result.session_token, "session-1")
        self.assertEqual(result.verification_delivery, "outbox")
        self.assertEqual(self.repository.audit_actions(), ["account_registered"])
        self.assertEqual(self.repository.cleared_limits, [("register", "127.0.0.1", "owner@example.test")])

    def test_register_consumes_limit_before_reporting_invalid_credentials(self):
        with self.assertRaisesRegex(AccountError, "Введите корректный email"):
            self.service.register("invalid", "password123", "Ученик", self.metadata)
        self.assertEqual(self.repository.rate_limit_calls[0][0], "register")
        self.assertEqual(self.repository.users, {})

    def test_rate_limit_error_carries_retry_after(self):
        self.repository.retry_after = 37
        with self.assertRaises(AccountError) as raised:
            self.service.login("user@example.test", "password123", self.metadata)
        self.assertEqual((raised.exception.reason, raised.exception.retry_after), ("rate_limited", 37))

    def test_login_failure_audits_without_creating_session(self):
        self.repository.add_user("user@example.test", "password123")
        with self.assertRaises(AccountError) as raised:
            self.service.login("USER@example.test", "wrong-password", self.metadata)
        self.assertEqual(raised.exception.reason, "invalid_credentials")
        self.assertEqual(self.repository.audit_actions(), ["login_failed"])
        self.assertEqual(self.repository.sessions, {})

    def test_login_success_creates_session_then_clears_limit_and_audits(self):
        self.repository.add_user("user@example.test", "password123")
        result = self.service.login(" USER@example.test ", "password123", self.metadata)
        self.assertEqual(result.session_token, "session-1")
        self.assertEqual(result.user["email"], "user@example.test")
        self.assertEqual(self.repository.audit_actions(), ["login_succeeded"])
        self.assertEqual(self.repository.cleared_limits, [("login", "127.0.0.1", "user@example.test")])

    def test_current_user_hides_password_hash_and_rejects_missing_token(self):
        self.assertIsNone(self.service.current_user(None))
        user_id = self.repository.add_user("user@example.test", "password123")
        self.repository.sessions["valid"] = user_id
        self.assertEqual(
            self.service.current_user("valid"),
            {"id": user_id, "email": "user@example.test", "displayName": "User", "role": "student", "emailVerified": False},
        )

    def test_logout_is_idempotent_and_audits_only_a_resolved_session(self):
        self.service.logout(None, self.metadata)
        self.service.logout("unknown", self.metadata)
        self.assertEqual(self.repository.audit_actions(), [])
        user_id = self.repository.add_user("user@example.test", "password123")
        self.repository.sessions["valid"] = user_id
        self.service.logout("valid", self.metadata)
        self.assertEqual(self.repository.audit_actions(), ["logout"])
        self.assertNotIn("valid", self.repository.sessions)
```

Also test duplicate-email translation to `AccountError("email_already_registered")`, display-name bounds `2..80`, registration password bounds `8..128`, and session expiry calculation `now + 30 * 86400`.
Every validation failure uses reason `invalid_input` and preserves the exact current Russian message.

- [ ] **Step 2: Run the new test module and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_account_application_service.AccountServiceCoreTest -v
```

Expected: import failure because `AccountService`, result dataclasses, and `AccountError` do not exist.

- [ ] **Step 3: Add the service core while temporarily retaining legacy free functions**

Add these public results and constructor:

```python
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
```

Implement a private `_now()` returning `int(self._clock())`, `_public_user(AccountProfile)`, `_audit(...)`, and `_consume_attempt(...)`. `_consume_attempt` opens its own repository transaction and raises:

```python
AccountError(
    "rate_limited",
    "Слишком много попыток. Попробуйте позже",
    retry_after=retry_after,
)
```

Implement exact transaction order:

- `register`: normalize/consume attempt; validate credentials and trimmed display name; transaction create user + issue verification token + `account_registered`; separate transaction create session; separate transaction clear registration limit; deliver link; return `RegistrationResult`.
- `login`: normalize/consume attempt; transaction read user; on mismatch separate audit transaction and raise `invalid_credentials`; on success separate session transaction followed by clear-limit + `login_succeeded` transaction; return `LoginResult`.
- `current_user(token: str | None)`: return `None` for no token, otherwise map `repository.current_user(token, now)` to the exact public payload.
- `logout`: no-op for no token; otherwise one transaction resolves identity, optionally writes `logout`, and deletes the token regardless of identity resolution.

Catch only `AccountConflictError` around registration mutation and translate it to:

```python
AccountError("email_already_registered", "Аккаунт с таким email уже существует")
```

Keep the existing free functions until Task 8 so the old controller and dependency path continue to run before cutover.

- [ ] **Step 4: Run service and existing domain tests**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_account_application_service.AccountServiceCoreTest tests.unit.test_account_service -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/trainer/services/accounts.py tests/unit/test_account_application_service.py
git commit -m "feat: add account authentication service"
```

---

### Task 3: Add email verification and password-reset use cases

**Files:**

- Modify: `src/trainer/services/accounts.py`
- Modify: `tests/unit/test_account_application_service.py`

**Interfaces:**

- Consumes: Task 2 `AccountService`, fake repository/sender, and `AccountLinkSender.send(kind, email, token)`.
- Produces: `request_email_verification()`, `confirm_email_verification()`, `request_password_reset()`, and `confirm_password_reset()`.

- [ ] **Step 1: Write failing verification and recovery tests**

Add tests that assert:

```python
class AccountServiceRecoveryTest(unittest.TestCase):
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

    def test_email_verification_request_rejects_verified_user_before_rate_limit(self):
        with self.assertRaises(AccountError) as raised:
            self.service.request_email_verification(1, "user@example.test", True, self.metadata)
        self.assertEqual(raised.exception.reason, "email_already_verified")
        self.assertEqual(self.repository.rate_limit_calls, [])

    def test_email_verification_request_replaces_token_audits_and_delivers(self):
        delivery = self.service.request_email_verification(7, "user@example.test", False, self.metadata)
        self.assertEqual(delivery, "outbox")
        self.assertEqual(
            self.sender.messages,
            [("email_verification", "user@example.test", "email_verification-7-1")],
        )
        self.assertEqual(self.repository.audit_actions(), ["email_verification_requested"])

    def test_delivery_failure_is_best_effort_and_audited(self):
        self.sender.error = OSError("smtp down")
        delivery = self.service.request_email_verification(7, "user@example.test", False, self.metadata)
        self.assertEqual(delivery, "failed")
        self.assertEqual(
            self.repository.audit_actions(),
            ["email_verification_requested", "email_delivery_failed"],
        )
        self.assertEqual(self.repository.written_audits[-1].details, {"kind": "email_verification"})

    def test_registration_delivery_failure_keeps_created_account_and_session(self):
        self.sender.error = OSError("smtp down")
        result = self.service.register("user@example.test", "password123", "Ученик", self.metadata)
        self.assertEqual(result.verification_delivery, "failed")
        self.assertIn(result.user["id"], self.repository.users)
        self.assertIn(result.session_token, self.repository.sessions)
        self.assertEqual(
            self.repository.audit_actions(),
            ["account_registered", "email_delivery_failed"],
        )

    def test_verification_confirm_consumes_token_updates_user_and_audits_atomically(self):
        user_id = self.repository.add_user("user@example.test", "password123")
        token = self.repository.seed_token("email_verification", user_id)
        self.service.confirm_email_verification(token, self.metadata)
        self.assertTrue(self.repository.users[user_id].email_verified_at)
        self.assertEqual(self.repository.audit_actions(), ["email_verified"])
        self.assertNotIn(token, self.repository.tokens)

    def test_password_reset_request_does_not_reveal_unknown_email(self):
        self.service.request_password_reset("unknown@example.test", self.metadata)
        self.assertEqual(self.sender.messages, [])
        self.assertEqual(self.repository.audit_actions(), ["password_reset_requested_unknown"])

    def test_password_reset_confirm_changes_hash_revokes_sessions_clears_limit_and_audits(self):
        user_id = self.repository.add_user("user@example.test", "old-password")
        token = self.repository.seed_token("password_reset", user_id)
        self.repository.sessions["old-session"] = user_id
        self.service.confirm_password_reset(token, "new-password123", self.metadata)
        self.assertTrue(password_matches("new-password123", self.repository.users[user_id].password_hash))
        self.assertEqual(self.repository.sessions, {})
        self.assertEqual(
            self.repository.cleared_limits,
            [("login", "127.0.0.1", "user@example.test")],
        )
        self.assertEqual(self.repository.audit_actions(), ["password_reset_completed"])
```

Also cover request rate limits, successful known-email reset delivery, invalid/expired token → `token_invalid`, and reset password bounds `8..128` checked before a transaction.

- [ ] **Step 2: Run the focused tests and verify missing-method failures**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_account_application_service.AccountServiceRecoveryTest -v
```

Expected: `AttributeError` for the four missing methods.

- [ ] **Step 3: Implement delivery and token workflows**

Add a private best-effort delivery helper with the current semantics:

```python
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
                AccountAuditEvent(
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
            extra={"event": "account_email_delivery_failed", "fields": {"kind": kind, "error": type(error).__name__}},
        )
        return "failed"
```

Route Task 2 registration delivery through `_deliver()` as well, so SMTP/outbox failure cannot reverse the already
committed user and session. Implement the four public methods with the transaction order and exact messages in the
spec. `request_password_reset()` always returns `None`; the controller owns the constant anti-enumeration
response. `confirm_password_reset()` must clear the `login` limit using the current request IP and the consumed
user's email in the same transaction as password/session/audit changes.

- [ ] **Step 4: Run all account application tests**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_account_application_service -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/trainer/services/accounts.py tests/unit/test_account_application_service.py
git commit -m "feat: add account recovery workflows"
```

---

### Task 4: Add audit retrieval and durable account deletion orchestration

**Files:**

- Modify: `src/trainer/services/accounts.py`
- Modify: `tests/unit/test_account_application_service.py`

**Interfaces:**

- Consumes: `AccountRepository.audit_events()`, session `enqueue_account_cleanup()`, `delete_user()`, and injected cleanup runner.
- Produces: `AccountService.audit_events(user_id)` and `delete_account(user_id, email, password, metadata)`.

- [ ] **Step 1: Write failing audit/deletion service tests**

Add tests with these exact contracts:

```python
class AccountServiceLifecycleTest(unittest.TestCase):
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

    def test_audit_events_preserve_public_field_names(self):
        self.repository.read_audit_events = [
            AccountAuditRecord("login_succeeded", "127.0.0.1", "agent", {"source": "test"}, 100)
        ]
        self.assertEqual(
            self.service.audit_events(7),
            [{
                "action": "login_succeeded",
                "ipAddress": "127.0.0.1",
                "userAgent": "agent",
                "details": {"source": "test"},
                "createdAt": 100,
            }],
        )
        self.assertEqual(self.repository.audit_limits, [(7, 50)])

    def test_invalid_deletion_password_commits_failed_audit_without_cleanup(self):
        user_id = self.repository.add_user("user@example.test", "correct-password")
        with self.assertRaises(AccountError) as raised:
            self.service.delete_account(user_id, "user@example.test", "wrong-password", self.metadata)
        self.assertEqual(raised.exception.reason, "invalid_password")
        self.assertEqual(self.repository.audit_actions(), ["account_deletion_failed"])
        self.assertIn(user_id, self.repository.users)
        self.assertEqual(self.repository.cleanup_enqueues, [])
        self.assertEqual(self.cleanup.calls, 0)

    def test_account_deletion_enqueues_and_deletes_in_one_transaction_then_runs_cleanup(self):
        user_id = self.repository.add_user("user@example.test", "correct-password")
        self.service.delete_account(user_id, "user@example.test", "correct-password", self.metadata)
        self.assertNotIn(user_id, self.repository.users)
        self.assertEqual(self.repository.cleanup_enqueues, [(user_id, 1_700_000_000)])
        self.assertEqual(self.repository.audit_actions(), ["account_deleted"])
        self.assertEqual(self.cleanup.calls, 1)
        self.assertEqual(
            self.repository.transactions[-1],
            ["user_by_id", "enqueue_account_cleanup", "audit:account_deleted", "delete_user"],
        )

    def test_cleanup_failure_does_not_reverse_committed_account_deletion(self):
        user_id = self.repository.add_user("user@example.test", "correct-password")
        self.cleanup.error = OSError("storage down")
        self.service.delete_account(user_id, "user@example.test", "correct-password", self.metadata)
        self.assertNotIn(user_id, self.repository.users)
        self.assertEqual(self.cleanup.calls, 1)
```

- [ ] **Step 2: Run and verify missing-method failures**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_account_application_service.AccountServiceLifecycleTest -v
```

Expected: `AttributeError` for `audit_events` and `delete_account`.

- [ ] **Step 3: Implement audit mapping and post-commit deletion**

`audit_events()` calls repository limit 50 and maps snake_case records to existing camelCase response fields.

`delete_account()` opens one transaction, resolves `user_by_id`, and does not raise inside the context for an invalid password. Instead it writes `account_deletion_failed`, exits the context so the audit commits, then raises:

```python
AccountError("invalid_password", "Неверный пароль")
```

For a valid password, in the same transaction call `enqueue_account_cleanup(user_id, now)`, write `account_deleted`, and call `delete_user(user_id)`. After the context commits, invoke `_cleanup_runner()` inside `try/except Exception`; log `completed`, `failed`, and `pending` on success and log only `userId` on failure. Never include storage keys in logs and never re-raise cleanup failure.

- [ ] **Step 4: Run the complete service suite**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_account_application_service tests.unit.test_account_service -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/trainer/services/accounts.py tests/unit/test_account_application_service.py
git commit -m "feat: add account lifecycle service"
```

---

### Task 5: Implement SQLite account repository core

**Files:**

- Create: `src/trainer/infrastructure/database/account_repository.py`
- Create: `tests/integration/test_account_repository.py`

**Interfaces:**

- Consumes: Task 1 repository Protocol and existing `RATE_LIMITS`, `TOKEN_TTL`, `consume_rate_limit`, `clear_rate_limit`, `issue_token`, `consume_token`, `record_audit`, and `audit_events` behavior.
- Produces: `SQLiteAccountRepository` and its transaction session for users, sessions, tokens, rate limits, and audit.

- [ ] **Step 1: Write failing SQLite adapter tests**

Create a temporary migrated SQLite database in `setUp`, instantiate `SQLiteAccountRepository(lambda: connect(self.database_path))`, and add tests for:

```python
def test_transaction_commits_and_rolls_back_user_and_audit_together(self):
    with self.repository.transaction() as transaction:
        user_id = transaction.create_user("user@example.test", "hash", "User", "student", 1000)
        transaction.audit(AccountAuditEvent("account_registered", self.metadata, 1000, user_id, "user@example.test"))
    with connect(self.database_path) as database:
        self.assertEqual(database.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        self.assertEqual(database.execute("SELECT action FROM audit_log").fetchone()[0], "account_registered")

    with self.assertRaisesRegex(RuntimeError, "rollback"):
        with self.repository.transaction() as transaction:
            transaction.create_user("rolled-back@example.test", "hash", "User", "student", 1001)
            raise RuntimeError("rollback")
    with connect(self.database_path) as database:
        self.assertIsNone(database.execute("SELECT id FROM users WHERE email=?", ("rolled-back@example.test",)).fetchone())

def test_duplicate_email_is_adapter_neutral(self):
    with self.repository.transaction() as transaction:
        transaction.create_user("same@example.test", "hash", "User", "student", 1000)
    with self.assertRaises(AccountConflictError):
        with self.repository.transaction() as transaction:
            transaction.create_user("same@example.test", "hash", "User", "student", 1001)

def test_session_stores_digest_and_current_user_honors_expiry(self):
    user_id = self.create_user()
    with self.repository.transaction() as transaction:
        token = transaction.create_session(user_id, 2000, 1000)
    with connect(self.database_path) as database:
        stored = database.execute("SELECT token_hash FROM sessions").fetchone()[0]
    self.assertNotEqual(stored, token)
    self.assertEqual(self.repository.current_user(token, 1999).id, user_id)
    self.assertIsNone(self.repository.current_user(token, 2000))

def test_rate_limit_persists_across_transactions_and_clear_removes_it(self):
    for offset in range(8):
        with self.repository.transaction() as transaction:
            self.assertEqual(transaction.consume_rate_limit("login", "127.0.0.1", "user@example.test", 1000 + offset), 0)
    with self.repository.transaction() as transaction:
        self.assertGreater(transaction.consume_rate_limit("login", "127.0.0.1", "user@example.test", 1008), 0)
        transaction.clear_rate_limit("login", "127.0.0.1", "user@example.test")
    with self.repository.transaction() as transaction:
        self.assertEqual(transaction.consume_rate_limit("login", "127.0.0.1", "user@example.test", 1009), 0)

def test_tokens_are_single_use_replace_previous_and_expire(self):
    user_id = self.create_user()
    with self.repository.transaction() as transaction:
        first = transaction.issue_token("password_reset", user_id, 1000)
        second = transaction.issue_token("password_reset", user_id, 1001)
    with self.repository.transaction() as transaction:
        self.assertIsNone(transaction.consume_token("password_reset", first, 1002))
        self.assertEqual(transaction.consume_token("password_reset", second, 1002).id, user_id)
        self.assertIsNone(transaction.consume_token("password_reset", second, 1003))
        expired = transaction.issue_token("email_verification", user_id, 1000)
    with self.repository.transaction() as transaction:
        self.assertIsNone(transaction.consume_token("email_verification", expired, 1000 + 86401))
```

Also test `user_by_email`, `user_by_id`, `session_identity`, `delete_session`, `verify_email`, `replace_password`, `delete_user_sessions`, audit normalization/truncation, and audit order/limit mapping.

- [ ] **Step 2: Run the repository tests and verify import failure**

Run:

```bash
.venv/bin/python -m unittest tests.integration.test_account_repository -v
```

Expected: import failure because `SQLiteAccountRepository` does not exist.

- [ ] **Step 3: Implement connection ownership and mappings**

Use an explicit context manager:

```python
class SQLiteAccountRepository:
    def __init__(self, connect_factory: Callable[[], sqlite3.Connection]):
        self._connect = connect_factory

    @contextmanager
    def transaction(self):
        database = self._connect()
        try:
            yield SQLiteAccountRepositorySession(database)
            database.commit()
        except Exception:
            database.rollback()
            raise
        finally:
            database.close()
```

Map DB rows into `AccountProfile`, `AccountRecord`, and `AccountIdentity`. Session and account-token methods generate `secrets.token_urlsafe(32)`, store only `token_digest(token)`, and return the raw token. Preserve `TOKEN_TTL` values in infrastructure. `create_user()` catches `INTEGRITY_ERRORS` only around the insert and raises `AccountConflictError` from the original error.

Implement read methods using `closing(self._connect())` so every connection closes. `audit_events()` may reuse the existing database helper, but must return typed `AccountAuditRecord` instances and preserve current JSON parsing, sort, and clamped limit.

- [ ] **Step 4: Run repository and existing account integration tests**

Run:

```bash
.venv/bin/python -m unittest tests.integration.test_account_repository tests.integration.test_accounts -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/trainer/infrastructure/database/account_repository.py tests/integration/test_account_repository.py
git commit -m "feat: add sqlite account repository"
```

---

### Task 6: Add atomic account cleanup enqueue to the SQLite adapter

**Files:**

- Modify: `src/trainer/infrastructure/database/account_repository.py`
- Modify: `tests/integration/test_account_repository.py`

**Interfaces:**

- Consumes: existing `account_review_storage_keys()` and `enqueue_cleanup_job()` durable cleanup primitives.
- Produces: `SQLiteAccountRepositorySession.enqueue_account_cleanup(user_id, now)` collecting every account-owned private key before cascade deletion.

- [ ] **Step 1: Write failing deletion transaction tests**

Seed one user with all five key sources: legacy `recordings.file_name`, `material_assets.storage_key`, `assignment_material_assets.storage_key`, `review_request_recordings.storage_key`, `review_request_assets.storage_key`, plus `personal_recordings.storage_key`. Add:

```python
def test_account_cleanup_collects_every_key_before_user_cascade(self):
    user_id, expected_audio, expected_material, expected_assignment = self.seed_account_storage_graph()
    with self.repository.transaction() as transaction:
        transaction.enqueue_account_cleanup(user_id, 2000)
        transaction.audit(AccountAuditEvent("account_deleted", self.metadata, 2000, user_id, "user@example.test"))
        transaction.delete_user(user_id)

    with connect(self.database_path) as database:
        self.assertIsNone(database.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone())
        job = database.execute(
            "SELECT audio_keys_json,material_keys_json,assignment_keys_json FROM storage_cleanup_jobs"
        ).fetchone()
        audit = database.execute("SELECT user_id,email,action FROM audit_log").fetchone()
    self.assertEqual(set(json.loads(job["audio_keys_json"])), expected_audio)
    self.assertEqual(set(json.loads(job["material_keys_json"])), expected_material)
    self.assertEqual(set(json.loads(job["assignment_keys_json"])), expected_assignment)
    self.assertEqual((audit["user_id"], audit["email"], audit["action"]), (None, "user@example.test", "account_deleted"))

def test_cleanup_job_and_user_delete_roll_back_together(self):
    user_id = self.create_user()
    with self.assertRaisesRegex(RuntimeError, "rollback"):
        with self.repository.transaction() as transaction:
            transaction.enqueue_account_cleanup(user_id, 2000)
            transaction.delete_user(user_id)
            raise RuntimeError("rollback")
    with connect(self.database_path) as database:
        self.assertIsNotNone(database.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone())
        self.assertEqual(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0], 0)
```

- [ ] **Step 2: Run the two tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.integration.test_account_repository.SQLiteAccountRepositoryTest.test_account_cleanup_collects_every_key_before_user_cascade tests.integration.test_account_repository.SQLiteAccountRepositoryTest.test_cleanup_job_and_user_delete_roll_back_together -v
```

Expected: failure because `enqueue_account_cleanup()` is not implemented.

- [ ] **Step 3: Move key collection into the adapter session**

Implement the same queries currently in `auth.account_delete()`. Deduplicate review/personal keys through the existing helper and enqueue exactly one job, even if every list is empty:

```python
enqueue_cleanup_job(
    self.database,
    audio_keys=[row["file_name"] for row in legacy_recordings] + review_audio_keys,
    material_keys=[row["storage_key"] for row in material_assets],
    assignment_keys=[row["storage_key"] for row in assignment_assets] + review_asset_keys,
    now=now,
)
```

Do not call `commit()`, `rollback()`, storage factory, or physical delete from the session method; the repository transaction owns commit and runtime cleanup owns object deletion.

- [ ] **Step 4: Run all repository tests**

Run:

```bash
.venv/bin/python -m unittest tests.integration.test_account_repository -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/trainer/infrastructure/database/account_repository.py tests/integration/test_account_repository.py
git commit -m "feat: enqueue account cleanup in repository"
```

---

### Task 7: Add account-link adapter, centralized configuration, and runtime composition

**Files:**

- Create: `src/trainer/infrastructure/mailer/account_links.py`
- Create: `tests/unit/test_account_link_sender.py`
- Modify: `src/trainer/config.py`
- Modify: `src/trainer/api/runtime.py`
- Modify: `src/trainer/api/dependencies.py`
- Modify: `tests/unit/test_account_links.py`
- Modify: `tests/unit/test_application_services.py`

**Interfaces:**

- Consumes: `AccountService`, `SQLiteAccountRepository`, `AccountLinkSender`, existing `send_email()`, and `process_cleanup_jobs()`.
- Produces: `MailAccountLinkSender`, config `account_public_url()`/`owner_email()`, runtime `account_service()`, and private `_process_account_cleanup()`.

- [ ] **Step 1: Write failing adapter/config/runtime tests**

Move `AccountPublicUrlTest` to import `account_public_url` from `trainer.config` and add owner normalization. In the new sender test patch `trainer.infrastructure.mailer.account_links.send_email` and assert:

```python
class AccountLinkSenderTest(unittest.TestCase):
    def test_verification_link_uses_verify_parameter_and_preserves_copy(self):
        sender = MailAccountLinkSender(Path("/private/data"), "https://trainer.example/")
        with patch("trainer.infrastructure.mailer.account_links.send_email", return_value="outbox") as send:
            delivery = sender.send("email_verification", "user@example.test", "token with space")
        self.assertEqual(delivery, "outbox")
        data_dir, recipient, subject, body = send.call_args.args
        self.assertEqual(data_dir, Path("/private/data"))
        self.assertEqual(recipient, "user@example.test")
        self.assertEqual(subject, "Подтвердите email — тренажёр ЕГЭ")
        self.assertIn("Ссылка действует 24 часа", body)
        self.assertIn("https://trainer.example/?verify=token%20with%20space", body)

    def test_password_reset_link_uses_reset_parameter_and_one_hour_copy(self):
        sender = MailAccountLinkSender(Path("/private/data"), "https://trainer.example")
        with patch("trainer.infrastructure.mailer.account_links.send_email", return_value="smtp") as send:
            self.assertEqual(sender.send("password_reset", "user@example.test", "secret"), "smtp")
        self.assertIn("Ссылка действует 1 час", send.call_args.args[3])
        self.assertIn("https://trainer.example/?reset=secret", send.call_args.args[3])
```

Add a runtime composition test that patches `SQLiteAccountRepository`, `MailAccountLinkSender`, and `AccountService`, calls `runtime.account_service()`, and verifies it passes current `connect`, `DATA_DIR`, config values, `SESSION_DAYS`, and a callable cleanup runner.

```python
class AccountServiceRuntimeTest(unittest.TestCase):
    def test_factory_composes_current_runtime_dependencies_without_cache(self):
        repository = object()
        sender = object()
        service = object()
        with (
            patch.object(runtime, "SQLiteAccountRepository", return_value=repository) as repository_type,
            patch.object(runtime, "MailAccountLinkSender", return_value=sender) as sender_type,
            patch.object(runtime, "AccountService", return_value=service) as service_type,
            patch.object(runtime, "account_public_url", return_value="https://trainer.example"),
            patch.object(runtime, "owner_email", return_value="owner@example.test"),
        ):
            first = runtime.account_service()
            second = runtime.account_service()
        self.assertIs(first, service)
        self.assertIs(second, service)
        self.assertEqual(repository_type.call_count, 2)
        repository_type.assert_called_with(runtime.connect)
        sender_type.assert_called_with(runtime.DATA_DIR, "https://trainer.example")
        service_type.assert_called_with(
            repository,
            sender,
            runtime._process_account_cleanup,
            owner_email="owner@example.test",
            session_days=runtime.SESSION_DAYS,
        )
```

- [ ] **Step 2: Run and verify import/attribute failures**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_account_links tests.unit.test_account_link_sender tests.unit.test_application_services.AccountServiceRuntimeTest -v
```

Expected: import failures for the config helpers/link sender or missing `runtime.account_service`.

- [ ] **Step 3: Implement configuration and mail adapter**

Add to `trainer.config`:

```python
def account_public_url() -> str:
    return os.environ.get("TRAINER_PUBLIC_URL", "").rstrip("/") or "http://127.0.0.1:8080"


def owner_email() -> str:
    return os.environ.get("TRAINER_OWNER_EMAIL", "").strip().lower()
```

Implement `MailAccountLinkSender` with constructor `(data_dir: Path, public_url: str)` and exact verification/reset subject/body from the current `send_account_link()` helper. Use `quote(token)` and `self.public_url.rstrip('/')`.

In dependencies, import/re-export `account_public_url` from config and implement `owner_email_from_env()` as a compatibility wrapper returning `owner_email()`. Do not switch `current_user_or_none()` yet; that happens atomically with controller cutover in Task 8.

- [ ] **Step 4: Implement runtime composition**

Add:

```python
def _process_account_cleanup() -> AccountCleanupSummary:
    with connect() as database:
        summary = process_cleanup_jobs(
            database,
            audio_root=AUDIO_DIR,
            material_root=MATERIAL_ASSET_DIR,
            assignment_root=REVIEW_ASSET_DIR,
        )
    return AccountCleanupSummary(summary.completed, summary.failed, summary.pending)


def account_service() -> AccountService:
    return AccountService(
        SQLiteAccountRepository(connect),
        MailAccountLinkSender(DATA_DIR, account_public_url()),
        _process_account_cleanup,
        owner_email=owner_email(),
        session_days=SESSION_DAYS,
    )
```

Keep the factory uncached. Patch targets in tests must be module globals under `trainer.api.runtime` so fixture changes to DB paths/directories still take effect.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_account_links tests.unit.test_account_link_sender tests.unit.test_application_services.AccountServiceRuntimeTest -v
```

Expected: all tests pass.

Commit:

```bash
git add src/trainer/infrastructure/mailer/account_links.py src/trainer/config.py src/trainer/api/runtime.py src/trainer/api/dependencies.py tests/unit/test_account_links.py tests/unit/test_account_link_sender.py tests/unit/test_application_services.py
git commit -m "feat: compose account service runtime"
```

---

### Task 8: Cut the API over to AccountService and remove legacy account helpers

**Files:**

- Create: `tests/unit/test_auth_controller.py`
- Modify: `src/trainer/api/controllers/auth.py`
- Modify: `src/trainer/api/dependencies.py`
- Modify: `src/trainer/services/accounts.py`
- Modify: `tests/unit/test_application_services.py`
- Modify: `tests/unit/test_architecture_boundaries.py`
- Modify: `tests/integration/test_accounts.py`
- Modify: `tests/integration/test_api_flows.py`

**Interfaces:**

- Consumes: runtime `account_service()` and every Task 2–4 application method.
- Produces: transport-only auth controller, complete `AccountError` mapping, and service-based session dependency.

- [ ] **Step 1: Write failing controller contract and final architecture tests**

Create a fake service injected by patching `trainer.api.controllers.auth.runtime.account_service`. Test successful `ActionResult` mapping for all ten controller functions. Include these table-driven errors:

```python
ERROR_CASES = (
    ("invalid_input", "Введите корректный email", HTTPStatus.BAD_REQUEST, "invalid_request"),
    ("email_already_registered", "Аккаунт с таким email уже существует", HTTPStatus.CONFLICT, "email_already_registered"),
    ("invalid_credentials", "Неверный email или пароль", HTTPStatus.UNAUTHORIZED, "invalid_credentials"),
    ("email_already_verified", "Email уже подтверждён", HTTPStatus.CONFLICT, "email_already_verified"),
    ("token_invalid", "Ссылка недействительна или устарела", HTTPStatus.BAD_REQUEST, "token_invalid"),
    ("invalid_password", "Неверный пароль", HTTPStatus.UNAUTHORIZED, "invalid_password"),
)

def test_semantic_errors_keep_public_contract(self):
    for reason, message, status, code in ERROR_CASES:
        with self.subTest(reason=reason):
            error = auth._api_error(AccountError(reason, message))
            self.assertEqual((error.status, error.code, error.message), (status, code, message))

def test_rate_limit_keeps_header_and_numeric_detail(self):
    error = auth._api_error(AccountError("rate_limited", "Слишком много попыток. Попробуйте позже", retry_after=37))
    self.assertEqual(error.status, HTTPStatus.TOO_MANY_REQUESTS)
    self.assertEqual(error.headers, {"Retry-After": "37"})
    self.assertEqual(error.details, {"retryAfter": 37})
```

Add final architecture tests:

```python
def test_auth_controller_has_no_database_storage_mailer_or_domain_access(self):
    path = PACKAGE / "api" / "controllers" / "auth.py"
    imports = file_imports(path)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    self.assertFalse(any(module.startswith("trainer.infrastructure") for module in imports), imports)
    self.assertFalse(any(module.startswith("trainer.domain") for module in imports), imports)
    self.assertNotIn("execute", calls)
    self.assertNotIn("runtime.connect", source)
    self.assertNotIn("process_cleanup_jobs", source)

def test_account_boundary_dependency_direction(self):
    service_imports = file_imports(PACKAGE / "services" / "accounts.py")
    adapter_imports = file_imports(PACKAGE / "infrastructure" / "database" / "account_repository.py")
    sender_imports = file_imports(PACKAGE / "infrastructure" / "mailer" / "account_links.py")
    self.assertFalse(any(module.startswith("trainer.api") for module in service_imports), service_imports)
    self.assertFalse(any(module.startswith("trainer.infrastructure") for module in service_imports), service_imports)
    self.assertNotIn("sqlite3", service_imports)
    self.assertFalse(any(module.startswith("trainer.api") for module in adapter_imports | sender_imports))
```

Extend the dependency architecture assertion so `dependencies.py` contains neither `connect` import/call nor `trainer.services.accounts` import.

- [ ] **Step 2: Run the new tests and verify failure against the legacy controller**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_auth_controller tests.unit.test_architecture_boundaries -v
```

Expected: controller tests fail because service delegation/error mapper is absent; architecture tests report current database/domain/service imports.

- [ ] **Step 3: Replace controller implementation with service delegation**

Create one mapping helper:

```python
_ERROR_STATUS_AND_CODE = {
    "invalid_input": (HTTPStatus.BAD_REQUEST, "invalid_request"),
    "email_already_registered": (HTTPStatus.CONFLICT, "email_already_registered"),
    "invalid_credentials": (HTTPStatus.UNAUTHORIZED, "invalid_credentials"),
    "email_already_verified": (HTTPStatus.CONFLICT, "email_already_verified"),
    "token_invalid": (HTTPStatus.BAD_REQUEST, "token_invalid"),
    "invalid_password": (HTTPStatus.UNAUTHORIZED, "invalid_password"),
    "rate_limited": (HTTPStatus.TOO_MANY_REQUESTS, "rate_limited"),
}


def _api_error(error: AccountError) -> ApiError:
    status, code = _ERROR_STATUS_AND_CODE[error.reason]
    if error.reason == "rate_limited":
        retry_after = int(error.retry_after or 0)
        return ApiError(code, error.message, status, headers={"Retry-After": str(retry_after)}, retryAfter=retry_after)
    return ApiError(code, error.message, status)
```

Each controller function catches `AccountError` only, calls `_api_error`, and raises the returned `ApiError` from the service error. Preserve exact result shapes:

- register: `{"user": result.user, "verificationDelivery": result.verification_delivery}`, status 201, session token;
- login: `{"user": result.user}`, session token;
- logout: `{"ok": True}`, `clear_session=True`;
- me: current existing behavior unchanged;
- verification request: `{"ok": True, "delivery": delivery}`;
- verification/reset confirms: `{"ok": True}`, reset confirm clears session;
- reset request: `{"ok": True, "message": "Если аккаунт существует, инструкция отправлена"}`;
- audit: `{"events": events}`;
- delete: `{"ok": True}`, `clear_session=True`.

Construct `AccountRequestMetadata(context.client_ip, context.user_agent)` inside the controller and pass scalar user fields to service methods.

- [ ] **Step 4: Switch dependencies and remove all legacy helpers**

Change:

```python
def current_user_or_none(request: Request) -> dict | None:
    return runtime.account_service().current_user(session_token(request))
```

Remove imports of `connect` and `trainer.services.accounts` from dependencies.

From `services/accounts.py`, remove the old free functions `create_session`, `current_user`, `user_for_token`, `audit`, `send_account_link`, and `delete_account_storage`, together with their infrastructure imports. Retain only the new service/results/error and pure service helpers. Remove `AccountStorageServiceTest` and the `delete_account_storage` import from `tests/unit/test_application_services.py`.

Update integration cleanup seams:

- replace `patch.object(auth, "process_cleanup_jobs", ...)` with `patch.object(runtime, "process_cleanup_jobs", ...)`;
- replace direct assignment/restoration of `auth.process_cleanup_jobs` with `patch.object(runtime, "process_cleanup_jobs", side_effect=...)` or a scoped context manager;
- when inspecting a job, the patched function receives the runtime-opened database and the same three root keyword arguments.

- [ ] **Step 5: Run controller, architecture, account, and full HTTP-flow tests**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_auth_controller tests.unit.test_architecture_boundaries tests.unit.test_account_application_service tests.integration.test_account_repository tests.integration.test_accounts tests.integration.test_api_flows tests.integration.test_asgi -v
```

Expected: all tests pass and no auth controller or dependency test opens SQLite directly.

- [ ] **Step 6: Commit**

```bash
git add src/trainer/api/controllers/auth.py src/trainer/api/dependencies.py src/trainer/services/accounts.py tests/unit/test_auth_controller.py tests/unit/test_application_services.py tests/unit/test_architecture_boundaries.py tests/integration/test_accounts.py tests/integration/test_api_flows.py
git commit -m "refactor: delegate account api to service"
```

---

### Task 9: Document, inspect, and verify the complete boundary

**Files:**

- Modify: `docs/architecture.md`
- Modify if verification exposes a contract gap: only files already listed in Tasks 1–8 and their corresponding tests.

**Interfaces:**

- Consumes: the complete account boundary from Tasks 1–8.
- Produces: updated architecture documentation and fresh mandatory verification evidence.

- [ ] **Step 1: Update architecture documentation**

Add an account boundary section containing this dependency flow:

```text
accounts routes/dependencies → auth controller → AccountService
AccountService → AccountRepository / AccountLinkSender / cleanup runner ports
runtime → SQLiteAccountRepository / MailAccountLinkSender / durable cleanup processor
```

Document that account deletion gathers and enqueues private keys in the same SQLite transaction as `account_deleted` and user deletion, while physical storage deletion starts only after commit and remains retryable.

- [ ] **Step 2: Run structural searches**

Run:

```bash
rg -n "\.execute\(|runtime\.connect|process_cleanup_jobs|trainer\.infrastructure|trainer\.domain" src/trainer/api/controllers/auth.py
rg -n "trainer\.infrastructure|trainer\.api|sqlite3" src/trainer/services/accounts.py src/trainer/services/account_repository.py
rg -n "trainer\.services\.accounts" src/trainer/infrastructure/database
rg -n "delete_account_storage|account_services\.(create_session|current_user|user_for_token|audit|send_account_link)" src tests
```

Expected: every command prints no matches. If a command finds a match, remove the obsolete dependency and add or strengthen the matching architecture test before continuing.

- [ ] **Step 3: Run focused regression tests once more**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_account_application_service tests.unit.test_auth_controller tests.unit.test_account_link_sender tests.integration.test_account_repository tests.integration.test_accounts -v
```

Expected: all tests pass.

- [ ] **Step 4: Run the mandatory full check**

Run:

```bash
make check
```

Expected: pre-commit, JavaScript unit tests, Python unit tests, Python integration tests, and coverage all complete with exit code 0.

- [ ] **Step 5: Request code review and resolve findings**

Use `superpowers:requesting-code-review` against the branch diff from the spec commit parent through `HEAD`. Require the reviewer to check transaction boundaries, audit durability, error/cookie compatibility, token secrecy, cleanup ordering, and dependency direction. For every actionable finding, first apply `superpowers:receiving-code-review`, add a regression test, observe it fail, implement the smallest correction, and rerun the affected suite.

- [ ] **Step 6: Commit documentation and any already-verified review corrections**

```bash
git add docs/architecture.md src tests
git commit -m "docs: document account service boundary"
```

If Step 5 required code corrections, commit each cohesive correction with its regression test before this
documentation commit. Do not combine unrelated reviewer findings.

- [ ] **Step 7: Rerun mandatory verification after the final commit**

Run:

```bash
make check
git status --short --branch
```

Expected: `make check` exits 0 and status contains no uncommitted files.
