#!/usr/bin/env python3
"""Local application server with SQLite-backed accounts and progress sync."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TRAINER_DATA_DIR", ROOT / "var")).resolve()
DB_PATH = DATA_DIR / "trainer.sqlite3"
SESSION_DAYS = 30
MAX_BODY = 1_000_000
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PASSWORD_ITERATIONS = 260_000
GROUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as database:
        database.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'student' CHECK(role IN ('student', 'teacher')),
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_progress (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                progress_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS study_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                join_code TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS group_members (
                group_id INTEGER NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                joined_at INTEGER NOT NULL,
                PRIMARY KEY(group_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
            CREATE INDEX IF NOT EXISTS groups_teacher_idx ON study_groups(teacher_id);
            CREATE INDEX IF NOT EXISTS members_user_idx ON group_members(user_id);
            """
        )
        columns = {row["name"] for row in database.execute("PRAGMA table_info(users)")}
        if "display_name" not in columns:
            database.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        if "role" not in columns:
            database.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'")
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))


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


class TrainerHandler(BaseHTTPRequestHandler):
    server_version = "ChineseEGETrainer/1.0"

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/health":
            self.send_json({"ok": True, "database": "sqlite"})
        elif route == "/api/auth/me":
            self.auth_me()
        elif route == "/api/progress":
            self.progress_get()
        elif route == "/api/teacher/dashboard":
            self.teacher_dashboard()
        elif route == "/api/student/groups":
            self.student_groups()
        elif route.startswith("/api/"):
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found")
        else:
            self.serve_static(route)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if not self.same_origin_request():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid request origin")
        elif route == "/api/auth/register":
            self.auth_register()
        elif route == "/api/auth/login":
            self.auth_login()
        elif route == "/api/auth/logout":
            self.auth_logout()
        elif route == "/api/teacher/groups":
            self.teacher_group_create()
        elif route == "/api/groups/join":
            self.group_join()
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found")

    def do_PUT(self) -> None:
        route = urlparse(self.path).path
        if not self.same_origin_request():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid request origin")
        elif route == "/api/progress":
            self.progress_put()
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found")

    def auth_register(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        email, password, error = self.validate_credentials(payload)
        if error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, error)
            return
        role = str(payload.get("role", "student"))
        display_name = str(payload.get("displayName", "")).strip()
        if role not in {"student", "teacher"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Выберите тип аккаунта")
            return
        if not 2 <= len(display_name) <= 80:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Укажите имя длиной от 2 до 80 символов")
            return
        try:
            with connect() as database:
                cursor = database.execute(
                    "INSERT INTO users(email, password_hash, display_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (email, password_hash(password), display_name, role, int(time.time())),
                )
                user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            self.send_error_json(HTTPStatus.CONFLICT, "Аккаунт с таким email уже существует")
            return
        token = self.create_session(user_id)
        self.send_json({"user": self.user_payload(user_id, email, display_name, role)}, HTTPStatus.CREATED, token)

    def auth_login(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        with connect() as database:
            user = database.execute(
                "SELECT id, email, password_hash, display_name, role FROM users WHERE email = ?", (email,)
            ).fetchone()
        if not user or not password_matches(password, user["password_hash"]):
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Неверный email или пароль")
            return
        token = self.create_session(user["id"])
        self.send_json({"user": self.user_payload(user["id"], user["email"], user["display_name"], user["role"])}, token=token)

    def auth_logout(self) -> None:
        token = self.session_token()
        if token:
            with connect() as database:
                database.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))
        self.send_json({"ok": True}, clear_cookie=True)

    def auth_me(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        self.send_json({"user": user})

    def progress_get(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        with connect() as database:
            row = database.execute(
                "SELECT progress_json, updated_at FROM user_progress WHERE user_id = ?", (user["id"],)
            ).fetchone()
        progress = json.loads(row["progress_json"]) if row else None
        self.send_json({"progress": progress, "updatedAt": row["updated_at"] if row else None})

    def progress_put(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        payload = self.read_json()
        if payload is None:
            return
        progress = payload.get("progress")
        if not isinstance(progress, dict) or progress.get("version") != 1:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid progress document")
            return
        runs = progress.get("runs", [])
        if not isinstance(runs, list) or len(runs) > 200:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Progress history is too large")
            return
        encoded = json.dumps(progress, ensure_ascii=False, separators=(",", ":"))
        now = int(time.time())
        with connect() as database:
            database.execute(
                """
                INSERT INTO user_progress(user_id, progress_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET progress_json = excluded.progress_json,
                    updated_at = excluded.updated_at
                """,
                (user["id"], encoded, now),
            )
        self.send_json({"ok": True, "updatedAt": now})

    def teacher_group_create(self) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        payload = self.read_json()
        if payload is None:
            return
        name = str(payload.get("name", "")).strip()
        if not 2 <= len(name) <= 80:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Название группы должно содержать от 2 до 80 символов")
            return
        with connect() as database:
            for _ in range(10):
                code = "".join(secrets.choice(GROUP_CODE_ALPHABET) for _ in range(6))
                try:
                    cursor = database.execute(
                        "INSERT INTO study_groups(teacher_id, name, join_code, created_at) VALUES (?, ?, ?, ?)",
                        (user["id"], name, code, int(time.time())),
                    )
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Не удалось создать код группы")
                return
        self.send_json({"group": {"id": cursor.lastrowid, "name": name, "code": code}}, HTTPStatus.CREATED)

    def group_join(self) -> None:
        user = self.require_role("student")
        if not user:
            return
        payload = self.read_json()
        if payload is None:
            return
        code = str(payload.get("code", "")).strip().upper().replace(" ", "")
        with connect() as database:
            group = database.execute(
                "SELECT id, name FROM study_groups WHERE join_code = ?", (code,)
            ).fetchone()
            if not group:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Группа с таким кодом не найдена")
                return
            database.execute(
                "INSERT OR IGNORE INTO group_members(group_id, user_id, joined_at) VALUES (?, ?, ?)",
                (group["id"], user["id"], int(time.time())),
            )
        self.send_json({"group": {"id": group["id"], "name": group["name"]}})

    def student_groups(self) -> None:
        user = self.require_role("student")
        if not user:
            return
        with connect() as database:
            rows = database.execute(
                """
                SELECT study_groups.id, study_groups.name, users.display_name AS teacher_name
                FROM group_members
                JOIN study_groups ON study_groups.id = group_members.group_id
                JOIN users ON users.id = study_groups.teacher_id
                WHERE group_members.user_id = ? ORDER BY study_groups.name
                """,
                (user["id"],),
            ).fetchall()
        self.send_json({"groups": [dict(row) for row in rows]})

    def teacher_dashboard(self) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        with connect() as database:
            groups = database.execute(
                "SELECT id, name, join_code, created_at FROM study_groups WHERE teacher_id = ? ORDER BY created_at DESC",
                (user["id"],),
            ).fetchall()
            result = []
            for group in groups:
                members = database.execute(
                    """
                    SELECT users.id, users.display_name, users.email, user_progress.progress_json,
                           user_progress.updated_at
                    FROM group_members
                    JOIN users ON users.id = group_members.user_id
                    LEFT JOIN user_progress ON user_progress.user_id = users.id
                    WHERE group_members.group_id = ? ORDER BY users.display_name, users.email
                    """,
                    (group["id"],),
                ).fetchall()
                students = []
                for member in members:
                    document = self.safe_progress(member["progress_json"])
                    completed = [run for run in document.get("runs", []) if run.get("status") == "completed"]
                    students.append({
                        "id": member["id"],
                        "name": member["display_name"] or member["email"],
                        "email": member["email"],
                        "completedRuns": len(completed),
                        "completedTasks": sum(len(run.get("completedTasks", [])) for run in completed),
                        "lastActivity": document.get("updatedAt") if member["progress_json"] else None,
                    })
                result.append({
                    "id": group["id"], "name": group["name"], "code": group["join_code"],
                    "createdAt": group["created_at"], "students": students,
                })
        self.send_json({"groups": result})

    @staticmethod
    def safe_progress(value: str | None) -> dict:
        if not value:
            return {"runs": []}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"runs": []}
        except json.JSONDecodeError:
            return {"runs": []}

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        expires = now + SESSION_DAYS * 86400
        with connect() as database:
            database.execute(
                "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token_digest(token), user_id, expires, now),
            )
        return token

    def current_user(self) -> dict | None:
        token = self.session_token()
        if not token:
            return None
        with connect() as database:
            row = database.execute(
                """
                SELECT users.id, users.email, users.display_name, users.role FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_digest(token), int(time.time())),
            ).fetchone()
        return self.user_payload(row["id"], row["email"], row["display_name"], row["role"]) if row else None

    @staticmethod
    def user_payload(user_id: int, email: str, display_name: str, role: str) -> dict:
        return {"id": user_id, "email": email, "displayName": display_name, "role": role}

    def require_role(self, role: str) -> dict | None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return None
        if user["role"] != role:
            self.send_error_json(HTTPStatus.FORBIDDEN, "Недостаточно прав")
            return None
        return user

    def session_token(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("trainer_session")
        return morsel.value if morsel else None

    def validate_credentials(self, payload: dict) -> tuple[str, str, str | None]:
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if len(email) > 254 or not EMAIL_RE.match(email):
            return email, password, "Введите корректный email"
        if len(password) < 8 or len(password) > 128:
            return email, password, "Пароль должен содержать от 8 до 128 символов"
        return email, password, None

    def read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid request body")
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return None
        if not isinstance(payload, dict):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "JSON object required")
            return None
        return payload

    def same_origin_request(self) -> bool:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if not origin or not host:
            return True
        parsed = urlparse(origin)
        return parsed.netloc == host and parsed.scheme in {"http", "https"}

    def serve_static(self, route: str) -> None:
        relative = unquote(route).lstrip("/") or "index.html"
        candidate = (ROOT / relative).resolve()
        if ROOT not in candidate.parents and candidate != ROOT:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if candidate.is_dir():
            candidate /= "index.html"
        if not candidate.is_file() or candidate == DATA_DIR or DATA_DIR in candidate.parents:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if candidate.suffix in {".html", ".js", ".css", ".json"} else "public, max-age=86400")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(data)

    def send_json(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
        token: str | None = None,
        clear_cookie: bool = False,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if token:
            cookie = f"trainer_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"
            if os.environ.get("TRAINER_SECURE_COOKIE") == "1":
                cookie += "; Secure"
            self.send_header("Set-Cookie", cookie)
        elif clear_cookie:
            self.send_header("Set-Cookie", "trainer_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
        self.end_headers()
        self.wfile.write(encoded)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Chinese EGE speaking trainer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    init_database()
    server = ThreadingHTTPServer((args.host, args.port), TrainerHandler)
    print(f"Trainer available at http://{args.host}:{args.port}")
    print(f"Database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
