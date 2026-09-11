from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from trainer.infrastructure.mailer import send_email
from trainer.services.account_repository import AccountLinkKind


class MailAccountLinkSender:
    def __init__(self, data_dir: Path, public_url: str):
        self.data_dir = data_dir
        self.public_url = public_url.rstrip("/")

    def send(self, kind: AccountLinkKind, email: str, token: str) -> str:
        parameter = "verify" if kind == "email_verification" else "reset"
        url = f"{self.public_url}/?{parameter}={quote(token)}"
        if kind == "email_verification":
            subject = "Подтвердите email — тренажёр ЕГЭ"
            body = f"Подтвердите адрес электронной почты. Ссылка действует 24 часа:\n\n{url}"
        else:
            subject = "Восстановление пароля — тренажёр ЕГЭ"
            body = f"Создайте новый пароль. Ссылка действует 1 час:\n\n{url}"
        return send_email(self.data_dir, email, subject, body)
