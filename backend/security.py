from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from urllib.parse import urlparse

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


def request_has_same_origin(host: str | None, origin: str | None, referer: str | None, fetch_site: str | None) -> bool:
    if not host or (fetch_site and fetch_site not in {"same-origin", "none"}):
        return False
    source = origin or referer
    if not source:
        return False
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host.lower()
