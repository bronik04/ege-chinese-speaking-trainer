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
        "SELECT attempts, window_started_at, blocked_until FROM auth_rate_limits WHERE kind = ? AND subject_hash = ?",
        (kind, subject),
    ).fetchone()
    if row and row["blocked_until"] > moment:
        return row["blocked_until"] - moment
    if not row or moment - row["window_started_at"] >= window:
        database.execute(
            """
            INSERT INTO auth_rate_limits(kind, subject_hash, attempts, window_started_at, blocked_until, updated_at)
            VALUES (?, ?, 1, ?, 0, ?)
            ON CONFLICT(kind, subject_hash) DO UPDATE SET attempts = 1,
                window_started_at = excluded.window_started_at, blocked_until = 0, updated_at = excluded.updated_at
            """,
            (kind, subject, moment, moment),
        )
        return 0
    if row["attempts"] >= limit:
        blocked_until = max(moment + 1, row["window_started_at"] + window)
        database.execute(
            "UPDATE auth_rate_limits SET blocked_until = ?, updated_at = ? WHERE kind = ? AND subject_hash = ?",
            (blocked_until, moment, kind, subject),
        )
        return blocked_until - moment
    database.execute(
        "UPDATE auth_rate_limits SET attempts = attempts + 1, updated_at = ? WHERE kind = ? AND subject_hash = ?",
        (moment, kind, subject),
    )
    return 0


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


def consume_token(
    database: sqlite3.Connection, kind: str, token: str, now: int | None = None
) -> sqlite3.Row | None:
    if not token or len(token) > 512:
        return None
    moment = int(time.time()) if now is None else int(now)
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = database.execute(
        """
        SELECT users.id, users.email, users.display_name, users.role, users.email_verified_at
        FROM account_tokens JOIN users ON users.id = account_tokens.user_id
        WHERE account_tokens.token_hash = ? AND account_tokens.kind = ? AND account_tokens.expires_at > ?
        """,
        (digest, kind, moment),
    ).fetchone()
    if row:
        database.execute("DELETE FROM account_tokens WHERE token_hash = ?", (digest,))
    return row


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
