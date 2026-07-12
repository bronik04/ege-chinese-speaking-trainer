from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time

RATE_LIMITS = {
    "login": (8, 60),
    "register": (5, 300),
    "password_reset": (5, 900),
    "email_verification": (5, 900),
}
TOKEN_TTL = {"email_verification": 24 * 60 * 60, "password_reset": 60 * 60}


def _subject_hash(client_ip: str, email: str) -> str:
    normalized = email.strip().lower()[:254]
    return hashlib.sha256(f"{client_ip}\0{normalized}".encode()).hexdigest()


def consume_rate_limit(
    database: sqlite3.Connection,
    kind: str,
    client_ip: str,
    email: str,
    now: int | None = None,
) -> int:
    limit, window = RATE_LIMITS[kind]
    moment = int(time.time()) if now is None else int(now)
    subject = _subject_hash(client_ip, email)
    row = database.execute(
        """
        INSERT INTO auth_rate_limits(kind,subject_hash,attempts,window_started_at,blocked_until,updated_at)
        VALUES (?,?,1,?,0,?)
        ON CONFLICT(kind,subject_hash) DO UPDATE SET
          attempts=CASE WHEN excluded.updated_at-auth_rate_limits.window_started_at>=? THEN 1
                        ELSE auth_rate_limits.attempts+1 END,
          window_started_at=CASE WHEN excluded.updated_at-auth_rate_limits.window_started_at>=?
                                 THEN excluded.updated_at ELSE auth_rate_limits.window_started_at END,
          blocked_until=CASE
            WHEN excluded.updated_at-auth_rate_limits.window_started_at>=? THEN 0
            WHEN auth_rate_limits.blocked_until>excluded.updated_at THEN auth_rate_limits.blocked_until
            WHEN auth_rate_limits.attempts>=? THEN
              CASE WHEN auth_rate_limits.window_started_at+?>excluded.updated_at
                   THEN auth_rate_limits.window_started_at+? ELSE excluded.updated_at+1 END
            ELSE 0 END,
          updated_at=excluded.updated_at
        RETURNING attempts,blocked_until
        """,
        (kind, subject, moment, moment, window, window, window, limit, window, window),
    ).fetchone()
    return max(0, int(row["blocked_until"]) - moment)


def clear_rate_limit(database: sqlite3.Connection, kind: str, client_ip: str, email: str) -> None:
    database.execute(
        "DELETE FROM auth_rate_limits WHERE kind = ? AND subject_hash = ?",
        (kind, _subject_hash(client_ip, email)),
    )


def issue_token(database: sqlite3.Connection, kind: str, user_id: int, now: int | None = None) -> str:
    moment = int(time.time()) if now is None else int(now)
    token = secrets.token_urlsafe(32)
    database.execute("DELETE FROM account_tokens WHERE user_id = ? AND kind = ?", (user_id, kind))
    database.execute(
        "INSERT INTO account_tokens(token_hash, user_id, kind, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (hashlib.sha256(token.encode()).hexdigest(), user_id, kind, moment + TOKEN_TTL[kind], moment),
    )
    return token


def consume_token(database: sqlite3.Connection, kind: str, token: str, now: int | None = None) -> sqlite3.Row | None:
    if not token or len(token) > 512:
        return None
    moment = int(time.time()) if now is None else int(now)
    digest = hashlib.sha256(token.encode()).hexdigest()
    consumed = database.execute(
        """
        DELETE FROM account_tokens
        WHERE token_hash = ? AND kind = ? AND expires_at > ?
        RETURNING user_id
        """,
        (digest, kind, moment),
    ).fetchone()
    if not consumed:
        return None
    return database.execute(
        "SELECT id,email,display_name,role,email_verified_at FROM users WHERE id = ?",
        (consumed["user_id"],),
    ).fetchone()


def record_audit(
    database: sqlite3.Connection,
    action: str,
    *,
    user_id: int | None = None,
    email: str | None = None,
    ip_address: str = "",
    user_agent: str = "",
    details: dict | None = None,
    now: int | None = None,
) -> None:
    database.execute(
        """
        INSERT INTO audit_log(user_id, email, action, ip_address, user_agent, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            email.strip().lower() if email else None,
            action,
            ip_address[:64],
            user_agent[:300],
            json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
            int(time.time()) if now is None else int(now),
        ),
    )


def audit_events(database: sqlite3.Connection, user_id: int, limit: int = 50) -> list[dict]:
    rows = database.execute(
        """
        SELECT action, ip_address, user_agent, details_json, created_at
        FROM audit_log WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?
        """,
        (user_id, min(max(limit, 1), 100)),
    ).fetchall()
    return [
        {
            "action": row["action"],
            "ipAddress": row["ip_address"],
            "userAgent": row["user_agent"],
            "details": json.loads(row["details_json"]),
            "createdAt": row["created_at"],
        }
        for row in rows
    ]
