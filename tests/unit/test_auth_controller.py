from __future__ import annotations

import unittest
from http import HTTPStatus
from unittest.mock import patch

from trainer.api.controllers import auth
from trainer.api.errors import ApiError
from trainer.api.results import RequestContext
from trainer.api.schemas import (
    DeleteAccountRequest,
    EmailRequest,
    LoginRequest,
    PasswordResetRequest,
    RegisterRequest,
    TokenRequest,
)
from trainer.services.account_repository import AccountRequestMetadata
from trainer.services.accounts import AccountError, LoginResult, RegistrationResult


class FakeAccountService:
    def __init__(self):
        self.calls: list[tuple] = []

    def register(self, email, password, display_name, metadata):
        self.calls.append(("register", email, password, display_name, metadata))
        return RegistrationResult(
            {
                "id": 7,
                "email": "student@example.test",
                "displayName": "Student",
                "role": "student",
                "emailVerified": False,
            },
            "register-session",
            "outbox",
        )

    def login(self, email, password, metadata):
        self.calls.append(("login", email, password, metadata))
        return LoginResult(
            {
                "id": 7,
                "email": "student@example.test",
                "displayName": "Student",
                "role": "student",
                "emailVerified": True,
            },
            "login-session",
        )

    def logout(self, token, metadata):
        self.calls.append(("logout", token, metadata))

    def request_email_verification(self, user_id, email, email_verified, metadata):
        self.calls.append(("request_email_verification", user_id, email, email_verified, metadata))
        return "smtp"

    def confirm_email_verification(self, token, metadata):
        self.calls.append(("confirm_email_verification", token, metadata))

    def request_password_reset(self, email, metadata):
        self.calls.append(("request_password_reset", email, metadata))

    def confirm_password_reset(self, token, password, metadata):
        self.calls.append(("confirm_password_reset", token, password, metadata))

    def audit_events(self, user_id):
        self.calls.append(("audit_events", user_id))
        return [{"action": "login_succeeded"}]

    def delete_account(self, user_id, email, password, metadata):
        self.calls.append(("delete_account", user_id, email, password, metadata))


class AuthControllerTest(unittest.TestCase):
    def setUp(self):
        self.service = FakeAccountService()
        self.context = RequestContext(client_ip="127.0.0.1", user_agent="controller-test")
        self.user = {
            "id": 7,
            "email": "student@example.test",
            "displayName": "Student",
            "role": "student",
            "emailVerified": False,
        }

    def test_all_account_actions_delegate_and_preserve_public_results(self):
        with patch.object(auth.runtime, "account_service", return_value=self.service):
            registered = auth.auth_register(
                RegisterRequest(
                    email="student@example.test",
                    password="password123",
                    displayName="Student",
                ),
                self.context,
            )
            logged_in = auth.auth_login(
                LoginRequest(email="student@example.test", password="password123"),
                self.context,
            )
            logged_out = auth.auth_logout("session", self.context)
            current = auth.auth_me(self.user)
            verification_requested = auth.email_verification_request(self.user, self.context)
            verification_confirmed = auth.email_verification_confirm(TokenRequest(token="verify"), self.context)
            reset_requested = auth.password_reset_request(EmailRequest(email="student@example.test"), self.context)
            reset_confirmed = auth.password_reset_confirm(
                PasswordResetRequest(token="reset", password="new-password"), self.context
            )
            audited = auth.account_audit(self.user)
            deleted = auth.account_delete(DeleteAccountRequest(password="password123"), self.user, self.context)

        self.assertEqual(registered.status, HTTPStatus.CREATED)
        self.assertEqual(registered.session_token, "register-session")
        self.assertEqual(
            registered.payload,
            {
                "user": {
                    "id": 7,
                    "email": "student@example.test",
                    "displayName": "Student",
                    "role": "student",
                    "emailVerified": False,
                },
                "verificationDelivery": "outbox",
            },
        )
        self.assertEqual(logged_in.session_token, "login-session")
        self.assertTrue(logged_in.payload["user"]["emailVerified"])
        self.assertEqual(logged_out.payload, {"ok": True})
        self.assertTrue(logged_out.clear_session)
        self.assertEqual(current.payload, {"user": self.user})
        self.assertEqual(verification_requested.payload, {"ok": True, "delivery": "smtp"})
        self.assertEqual(verification_confirmed.payload, {"ok": True})
        self.assertEqual(
            reset_requested.payload,
            {"ok": True, "message": "Если аккаунт существует, инструкция отправлена"},
        )
        self.assertEqual(reset_confirmed.payload, {"ok": True})
        self.assertTrue(reset_confirmed.clear_session)
        self.assertEqual(audited.payload, {"events": [{"action": "login_succeeded"}]})
        self.assertEqual(deleted.payload, {"ok": True})
        self.assertTrue(deleted.clear_session)
        self.assertEqual(
            [call[0] for call in self.service.calls],
            [
                "register",
                "login",
                "logout",
                "request_email_verification",
                "confirm_email_verification",
                "request_password_reset",
                "confirm_password_reset",
                "audit_events",
                "delete_account",
            ],
        )
        metadata_calls = [call for call in self.service.calls if call[0] not in {"audit_events"}]
        self.assertTrue(
            all(
                call[-1] == AccountRequestMetadata(self.context.client_ip, self.context.user_agent)
                for call in metadata_calls
            )
        )

    def test_account_errors_are_translated_to_stable_api_errors(self):
        cases = (
            ("invalid_input", "Введите корректный email", 400, "invalid_request"),
            ("email_already_registered", "Аккаунт уже существует", 409, "email_already_registered"),
            ("invalid_credentials", "Неверный email или пароль", 401, "invalid_credentials"),
            ("email_already_verified", "Email уже подтверждён", 409, "email_already_verified"),
            ("token_invalid", "Ссылка недействительна", 400, "token_invalid"),
            ("invalid_password", "Неверный пароль", 401, "invalid_password"),
        )
        for reason, message, status, code in cases:
            with self.subTest(reason=reason):
                translated = auth._api_error(AccountError(reason, message))
                self.assertEqual((translated.status, translated.code, translated.message), (status, code, message))

    def test_rate_limit_translation_preserves_retry_metadata(self):
        translated = auth._api_error(
            AccountError("rate_limited", "Слишком много попыток. Попробуйте позже", retry_after=37)
        )

        self.assertIsInstance(translated, ApiError)
        self.assertEqual(translated.status, HTTPStatus.TOO_MANY_REQUESTS)
        self.assertEqual(translated.code, "rate_limited")
        self.assertEqual(translated.headers, {"Retry-After": "37"})
        self.assertEqual(translated.details, {"retryAfter": 37})


if __name__ == "__main__":
    unittest.main()
