from __future__ import annotations

import os

from trainer.api.runtime import SESSION_DAYS


def session_cookie(token: str) -> str:
    cookie = f"trainer_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"
    if os.environ.get("TRAINER_SECURE_COOKIE") == "1":
        cookie += "; Secure"
    return cookie


def cleared_session_cookie() -> str:
    return "trainer_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
