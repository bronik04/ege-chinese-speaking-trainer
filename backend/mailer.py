from __future__ import annotations

import json
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path


def send_email(data_dir: Path, recipient: str, subject: str, body: str) -> str:
    host = os.environ.get("TRAINER_SMTP_HOST")
    if not host:
        outbox = data_dir / "outbox.log"
        outbox.parent.mkdir(parents=True, exist_ok=True)
        with outbox.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "to": recipient, "subject": subject, "body": body, "createdAt": int(time.time())
            }, ensure_ascii=False) + "\n")
        outbox.chmod(0o600)
        return "outbox"

    message = EmailMessage()
    message["From"] = os.environ.get("TRAINER_SMTP_FROM", "noreply@example.test")
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    port = int(os.environ.get("TRAINER_SMTP_PORT", "465"))
    username = os.environ.get("TRAINER_SMTP_USER")
    password = os.environ.get("TRAINER_SMTP_PASSWORD")
    if os.environ.get("TRAINER_SMTP_SSL", "1") == "1":
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as client:
            if username:
                client.login(username, password or "")
            client.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as client:
            if os.environ.get("TRAINER_SMTP_STARTTLS", "1") == "1":
                client.starttls(context=ssl.create_default_context())
            if username:
                client.login(username, password or "")
            client.send_message(message)
    return "smtp"
