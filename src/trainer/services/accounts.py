from __future__ import annotations

import secrets
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import quote

from trainer.domain.accounts import token_digest
from trainer.infrastructure.database.accounts import record_audit
from trainer.infrastructure.mailer import send_email
from trainer.infrastructure.storage import storage_from_env


def user_payload(user_id: int, email: str, display_name: str, role: str, email_verified_at: int | None) -> dict:
    return {
        "id": user_id,
        "email": email,
        "displayName": display_name,
        "role": role,
        "emailVerified": email_verified_at is not None,
    }


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
    for root, keys in (
        (audio_root, audio_keys),
        (material_root, material_keys),
        (assignment_root, assignment_keys),
    ):
        storage = storage_from_env(root)
        for key in keys:
            with suppress(Exception):
                storage.delete(key)
