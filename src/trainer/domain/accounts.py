from __future__ import annotations

import hashlib
import hmac
import os
import secrets

PASSWORD_ITERATIONS = 260_000


def email_in_allowlist(email: str, variable: str) -> bool:
    allowed = {item.strip().lower() for item in os.environ.get(variable, "").split(",") if item.strip()}
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
