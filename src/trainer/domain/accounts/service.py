from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Mapping

PASSWORD_ITERATIONS = 260_000
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    code: str | None = None
    message: str | None = None


def email_in_allowlist(email: str, configured_emails: str) -> bool:
    allowed = {item.strip().lower() for item in configured_emails.split(",") if item.strip()}
    return email.strip().lower() in allowed


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        iterations_text, salt_hex, digest_hex = encoded.split("$", 2)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations_text))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_credentials(email: str, password: str) -> tuple[str, str, str | None]:
    normalized_email = str(email).strip().lower()
    normalized_password = str(password)
    if len(normalized_email) > 254 or not EMAIL_RE.match(normalized_email):
        return normalized_email, normalized_password, "Введите корректный email"
    if len(normalized_password) < 8 or len(normalized_password) > 128:
        return normalized_email, normalized_password, "Пароль должен содержать от 8 до 128 символов"
    return normalized_email, normalized_password, None


def authorize_role(
    user: Mapping[str, object] | None,
    required_role: str,
    *,
    teacher_emails: str = "",
) -> AccessDecision:
    if not user:
        return AccessDecision(False, "authentication_required", "Authentication required")
    if user.get("role") != required_role:
        return AccessDecision(False, "insufficient_permissions", "Недостаточно прав")
    if required_role == "teacher" and not user.get("emailVerified"):
        return AccessDecision(
            False, "email_verification_required", "Подтвердите email для доступа к кабинету преподавателя"
        )
    if required_role == "teacher" and not email_in_allowlist(str(user.get("email", "")), teacher_emails):
        return AccessDecision(False, "teacher_not_allowed", "Роль преподавателя недоступна")
    return AccessDecision(True)
