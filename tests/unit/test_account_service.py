from __future__ import annotations

import unittest

from trainer.domain.accounts import PASSWORD_ITERATIONS, authorize_role, email_in_allowlist, validate_credentials


class AccountDomainServiceTest(unittest.TestCase):
    def test_preserves_password_iteration_export(self):
        self.assertEqual(PASSWORD_ITERATIONS, 260_000)

    def test_validate_credentials_normalizes_email_and_rejects_invalid_values(self):
        self.assertEqual(
            validate_credentials("  USER@Example.Test ", "password-123"),
            ("user@example.test", "password-123", None),
        )
        self.assertEqual(validate_credentials("invalid", "password-123")[2], "Введите корректный email")
        self.assertEqual(
            validate_credentials("user@example.test", "short")[2],
            "Пароль должен содержать от 8 до 128 символов",
        )

    def test_authorize_role_returns_transport_independent_decision(self):
        self.assertEqual(authorize_role(None, "student").code, "authentication_required")
        self.assertEqual(authorize_role({"role": "student"}, "teacher").code, "insufficient_permissions")
        self.assertEqual(
            authorize_role({"role": "teacher", "emailVerified": False}, "teacher").code,
            "email_verification_required",
        )
        allowed = authorize_role(
            {"role": "teacher", "email": "teacher@example.test", "emailVerified": True},
            "teacher",
            teacher_emails="teacher@example.test",
        )
        self.assertTrue(allowed.allowed)
        self.assertIsNone(allowed.code)

    def test_allowlist_is_pure_and_uses_explicit_values(self):
        self.assertTrue(email_in_allowlist("Teacher@Example.Test", "other@example.test,teacher@example.test"))
        self.assertFalse(email_in_allowlist("teacher@example.test", "other@example.test"))


if __name__ == "__main__":
    unittest.main()
