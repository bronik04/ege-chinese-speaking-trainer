from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from trainer.infrastructure.mailer.account_links import MailAccountLinkSender


class AccountLinkSenderTest(unittest.TestCase):
    def test_verification_link_uses_verify_parameter_and_preserves_copy(self):
        sender = MailAccountLinkSender(Path("/private/data"), "https://trainer.example/")

        with patch(
            "trainer.infrastructure.mailer.account_links.send_email",
            return_value="outbox",
        ) as send:
            delivery = sender.send(
                "email_verification",
                "user@example.test",
                "token with space",
            )

        self.assertEqual(delivery, "outbox")
        data_dir, recipient, subject, body = send.call_args.args
        self.assertEqual(data_dir, Path("/private/data"))
        self.assertEqual(recipient, "user@example.test")
        self.assertEqual(subject, "Подтвердите email — тренажёр ЕГЭ")
        self.assertIn("Ссылка действует 24 часа", body)
        self.assertIn("https://trainer.example/?verify=token%20with%20space", body)

    def test_password_reset_link_uses_reset_parameter_and_one_hour_copy(self):
        sender = MailAccountLinkSender(Path("/private/data"), "https://trainer.example")

        with patch(
            "trainer.infrastructure.mailer.account_links.send_email",
            return_value="smtp",
        ) as send:
            delivery = sender.send("password_reset", "user@example.test", "secret")

        self.assertEqual(delivery, "smtp")
        self.assertIn("Ссылка действует 1 час", send.call_args.args[3])
        self.assertIn("https://trainer.example/?reset=secret", send.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
