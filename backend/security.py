from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import urlparse

PASSWORD_ITERATIONS = 260_000
AUTH_RATE_LIMITS = {"login": (8, 60), "register": (5, 300)}
AUTH_ATTEMPTS: dict[tuple[str, str, str], list[float]] = {}
AUTH_ATTEMPTS_LOCK = threading.Lock()


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        iterations_text, salt_hex, digest_hex = encoded.split("$", 2)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations_text)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def auth_rate_limit(kind: str, client_ip: str, email: str, now: float | None = None) -> int:
    limit, window = AUTH_RATE_LIMITS[kind]
    moment = time.time() if now is None else now
    key = (kind, client_ip, email.strip().lower()[:254])
    with AUTH_ATTEMPTS_LOCK:
        recent = [stamp for stamp in AUTH_ATTEMPTS.get(key, []) if moment - stamp < window]
        if len(recent) >= limit:
            AUTH_ATTEMPTS[key] = recent
            return max(1, int(window - (moment - recent[0]) + 0.999))
        recent.append(moment)
        AUTH_ATTEMPTS[key] = recent
        if len(AUTH_ATTEMPTS) > 10_000:
            AUTH_ATTEMPTS.pop(next(iter(AUTH_ATTEMPTS)))
    return 0


def clear_auth_rate_limit(kind: str, client_ip: str, email: str) -> None:
    key = (kind, client_ip, email.strip().lower()[:254])
    with AUTH_ATTEMPTS_LOCK:
        AUTH_ATTEMPTS.pop(key, None)


def request_has_same_origin(host: str | None, origin: str | None, referer: str | None, fetch_site: str | None) -> bool:
    if not host or (fetch_site and fetch_site not in {"same-origin", "none"}):
        return False
    source = origin or referer
    if not source:
        return False
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host.lower()
