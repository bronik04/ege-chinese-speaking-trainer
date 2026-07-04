#!/usr/bin/env python3
"""Local application server with SQLite-backed accounts and progress sync."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import subprocess
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from backend.accounts import (
    audit_events,
    clear_rate_limit,
    consume_rate_limit,
    consume_token,
    issue_token,
    record_audit,
)
from backend.audio import validate_duration
from backend.database import connect as database_connect
from backend.database import initialize as initialize_database
from backend.exports import submissions_csv, submissions_pdf
from backend.grading import validate_scores
from backend.mailer import send_email
from backend.queries import (
    student_assignments,
    submission_history,
    teacher_assignments,
    teacher_dashboard,
    teacher_submissions,
)
from backend.security import (
    password_hash,
    password_matches,
    request_has_same_origin,
    token_digest,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TRAINER_DATA_DIR", ROOT / "var")).resolve()
DB_PATH = DATA_DIR / "trainer.sqlite3"
AUDIO_DIR = DATA_DIR / "audio"
SESSION_DAYS = 30
MAX_BODY = int(os.environ.get("TRAINER_MAX_JSON_BYTES", "1000000"))
MAX_AUDIO_BODY = int(os.environ.get("TRAINER_MAX_AUDIO_BYTES", "15000000"))
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
GROUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def connect() -> sqlite3.Connection:
    return database_connect(DB_PATH)


def init_database() -> None:
    initialize_database(DATA_DIR, AUDIO_DIR, DB_PATH)


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
        elif route == "/api/student/assignments":
            self.student_assignments()
        elif route == "/api/teacher/submissions":
            self.teacher_submissions()
        elif route == "/api/teacher/assignments":
            self.teacher_assignments()
        elif match := re.fullmatch(r"/api/teacher/submissions/(\d+)", route):
            self.submission_history(int(match.group(1)))
        elif route == "/api/teacher/export.csv":
            self.teacher_export("csv")
        elif route == "/api/teacher/export.pdf":
            self.teacher_export("pdf")
        elif route == "/api/account/audit":
            self.account_audit()
        elif re.fullmatch(r"/api/recordings/\d+", route):
            self.recording_get(int(route.rsplit("/", 1)[1]))
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
        elif route == "/api/auth/email/request":
            self.email_verification_request()
        elif route == "/api/auth/email/confirm":
            self.email_verification_confirm()
        elif route == "/api/auth/password/request":
            self.password_reset_request()
        elif route == "/api/auth/password/reset":
            self.password_reset_confirm()
        elif route == "/api/teacher/groups":
            self.teacher_group_create()
        elif route == "/api/groups/join":
            self.group_join()
        elif route == "/api/teacher/assignments":
            self.teacher_assignment_create()
        elif match := re.fullmatch(r"/api/teacher/assignments/(\d+)/resend", route):
            self.teacher_assignment_resend(int(match.group(1)))
        elif match := re.fullmatch(r"/api/assignments/(\d+)/submissions", route):
            self.submission_create(int(match.group(1)))
        elif match := re.fullmatch(r"/api/submissions/(\d+)/recordings", route):
            self.recording_create(int(match.group(1)))
        elif match := re.fullmatch(r"/api/submissions/(\d+)/review", route):
            self.review_submission(int(match.group(1)))
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found")

    def do_DELETE(self) -> None:
        route = urlparse(self.path).path
        if not self.same_origin_request():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid request origin")
        elif route == "/api/account":
            self.account_delete()
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found")

    def do_PUT(self) -> None:
        route = urlparse(self.path).path
        if not self.same_origin_request():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid request origin")
        elif route == "/api/progress":
            self.progress_put()
        elif match := re.fullmatch(r"/api/teacher/assignments/(\d+)", route):
            self.teacher_assignment_update(int(match.group(1)))
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found")

    def auth_register(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        email, password, error = self.validate_credentials(payload)
        if not self.allow_auth_attempt("register", email):
            return
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
                verification_token = issue_token(database, "email_verification", user_id)
                self.audit(database, "account_registered", user_id=user_id, email=email, details={"role": role})
        except sqlite3.IntegrityError:
            self.send_error_json(HTTPStatus.CONFLICT, "Аккаунт с таким email уже существует")
            return
        token = self.create_session(user_id)
        with connect() as database:
            clear_rate_limit(database, "register", self.client_address[0], email)
        delivery = self.send_account_link("email_verification", email, verification_token)
        self.send_json(
            {"user": self.user_payload(user_id, email, display_name, role, None), "verificationDelivery": delivery},
            HTTPStatus.CREATED,
            token,
        )

    def auth_login(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if not self.allow_auth_attempt("login", email):
            return
        with connect() as database:
            user = database.execute(
                "SELECT id, email, password_hash, display_name, role, email_verified_at FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        if not user or not password_matches(password, user["password_hash"]):
            with connect() as database:
                self.audit(database, "login_failed", user_id=user["id"] if user else None, email=email)
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Неверный email или пароль")
            return
        token = self.create_session(user["id"])
        with connect() as database:
            clear_rate_limit(database, "login", self.client_address[0], email)
            self.audit(database, "login_succeeded", user_id=user["id"], email=email)
        self.send_json({"user": self.user_payload(
            user["id"], user["email"], user["display_name"], user["role"], user["email_verified_at"]
        )}, token=token)

    def allow_auth_attempt(self, kind: str, email: str) -> bool:
        with connect() as database:
            retry_after = consume_rate_limit(database, kind, self.client_address[0], email)
        if not retry_after:
            return True
        self.send_json(
            {"error": "Слишком много попыток. Попробуйте позже", "retryAfter": retry_after},
            HTTPStatus.TOO_MANY_REQUESTS,
            extra_headers={"Retry-After": str(retry_after)},
        )
        return False

    def auth_logout(self) -> None:
        token = self.session_token()
        if token:
            with connect() as database:
                user = self.user_for_token(database, token)
                if user:
                    self.audit(database, "logout", user_id=user["id"], email=user["email"])
                database.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))
        self.send_json({"ok": True}, clear_cookie=True)

    def auth_me(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        self.send_json({"user": user})

    def email_verification_request(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        if user["emailVerified"]:
            self.send_error_json(HTTPStatus.CONFLICT, "Email уже подтверждён")
            return
        if not self.allow_auth_attempt("email_verification", user["email"]):
            return
        with connect() as database:
            token = issue_token(database, "email_verification", user["id"])
            self.audit(database, "email_verification_requested", user_id=user["id"], email=user["email"])
        delivery = self.send_account_link("email_verification", user["email"], token)
        self.send_json({"ok": True, "delivery": delivery})

    def email_verification_confirm(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        token = str(payload.get("token", ""))
        with connect() as database:
            user = consume_token(database, "email_verification", token)
            if not user:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Ссылка недействительна или устарела")
                return
            verified_at = int(time.time())
            database.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (verified_at, user["id"]))
            self.audit(database, "email_verified", user_id=user["id"], email=user["email"])
        self.send_json({"ok": True})

    def password_reset_request(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        email = str(payload.get("email", "")).strip().lower()
        if not self.allow_auth_attempt("password_reset", email):
            return
        with connect() as database:
            user = database.execute("SELECT id, email FROM users WHERE email = ?", (email,)).fetchone()
            if user:
                token = issue_token(database, "password_reset", user["id"])
                self.audit(database, "password_reset_requested", user_id=user["id"], email=email)
            else:
                token = None
                self.audit(database, "password_reset_requested_unknown", email=email)
        if token:
            self.send_account_link("password_reset", email, token)
        self.send_json({"ok": True, "message": "Если аккаунт существует, инструкция отправлена"})

    def password_reset_confirm(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        token = str(payload.get("token", ""))
        password = str(payload.get("password", ""))
        if not 8 <= len(password) <= 128:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Пароль должен содержать от 8 до 128 символов")
            return
        with connect() as database:
            user = consume_token(database, "password_reset", token)
            if not user:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Ссылка недействительна или устарела")
                return
            database.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash(password), user["id"]))
            database.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
            clear_rate_limit(database, "login", self.client_address[0], user["email"])
            self.audit(database, "password_reset_completed", user_id=user["id"], email=user["email"])
        self.send_json({"ok": True}, clear_cookie=True)

    def account_audit(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        with connect() as database:
            events = audit_events(database, user["id"])
        self.send_json({"events": events})

    def account_delete(self) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        payload = self.read_json()
        if payload is None:
            return
        password = str(payload.get("password", ""))
        with connect() as database:
            row = database.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
            if not row or not password_matches(password, row["password_hash"]):
                self.audit(database, "account_deletion_failed", user_id=user["id"], email=user["email"])
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Неверный пароль")
                return
            files = database.execute(
                """
                SELECT recordings.file_name FROM recordings
                JOIN submissions ON submissions.id = recordings.submission_id
                JOIN assignments ON assignments.id = submissions.assignment_id
                WHERE submissions.student_id = ? OR assignments.teacher_id = ?
                """,
                (user["id"], user["id"]),
            ).fetchall()
            self.audit(database, "account_deleted", user_id=user["id"], email=user["email"])
            database.execute("DELETE FROM users WHERE id = ?", (user["id"],))
        self.delete_audio_files([row["file_name"] for row in files])
        self.send_json({"ok": True}, clear_cookie=True)

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
                    self.audit(
                        database, "group_created", user_id=user["id"], email=user["email"],
                        details={"groupId": cursor.lastrowid, "name": name},
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
            self.audit(
                database, "group_joined", user_id=user["id"], email=user["email"],
                details={"groupId": group["id"], "name": group["name"]},
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
            result = teacher_dashboard(database, user["id"])
        self.send_json({"groups": result})

    def teacher_assignment_create(self) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        payload = self.read_json()
        if payload is None:
            return
        try:
            group_id = int(payload.get("groupId"))
        except (TypeError, ValueError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Выберите учебную группу")
            return
        title = str(payload.get("title", "")).strip()
        variant_id = str(payload.get("variantId", "")).strip()
        raw_tasks = payload.get("tasks", [])
        due_at = payload.get("dueAt")
        if not 2 <= len(title) <= 100 or not re.fullmatch(r"[a-z0-9-]{3,40}", variant_id):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Проверьте название и вариант")
            return
        if not isinstance(raw_tasks, list) or not raw_tasks:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Выберите хотя бы одно задание")
            return
        try:
            tasks = sorted(set(int(task) for task in raw_tasks))
            due_at = int(due_at) if due_at is not None else None
        except (TypeError, ValueError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Некорректные параметры задания")
            return
        if any(task not in {1, 2, 3} for task in tasks):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Допустимы задания 1–3")
            return
        with connect() as database:
            group = database.execute(
                "SELECT id FROM study_groups WHERE id = ? AND teacher_id = ?", (group_id, user["id"])
            ).fetchone()
            if not group:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Группа не найдена")
                return
            cursor = database.execute(
                """
                INSERT INTO assignments(group_id, teacher_id, title, variant_id, tasks_json, due_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (group_id, user["id"], title, variant_id, json.dumps(tasks), due_at, int(time.time()), int(time.time())),
            )
            self.audit(
                database, "assignment_created", user_id=user["id"], email=user["email"],
                details={"assignmentId": cursor.lastrowid, "groupId": group_id, "variantId": variant_id},
            )
        self.send_json({"assignment": {"id": cursor.lastrowid, "title": title}}, HTTPStatus.CREATED)

    def student_assignments(self) -> None:
        user = self.require_role("student")
        if not user:
            return
        with connect() as database:
            result = student_assignments(database, user["id"])
        self.send_json({"assignments": result})

    def teacher_assignments(self) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        with connect() as database:
            result = teacher_assignments(database, user["id"])
        self.send_json({"assignments": result})

    def teacher_assignment_update(self, assignment_id: int) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        payload = self.read_json()
        if payload is None:
            return
        title = str(payload.get("title", "")).strip()
        due_at = payload.get("dueAt")
        if not 2 <= len(title) <= 100:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Название должно содержать от 2 до 100 символов")
            return
        try:
            due_at = int(due_at) if due_at is not None else None
        except (TypeError, ValueError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Некорректный срок")
            return
        with connect() as database:
            cursor = database.execute(
                "UPDATE assignments SET title = ?, due_at = ?, updated_at = ? WHERE id = ? AND teacher_id = ?",
                (title, due_at, int(time.time()), assignment_id, user["id"]),
            )
            if not cursor.rowcount:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Задание не найдено")
                return
        self.send_json({"ok": True})

    def teacher_assignment_resend(self, assignment_id: int) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        with connect() as database:
            source = database.execute("SELECT * FROM assignments WHERE id = ? AND teacher_id = ?", (assignment_id, user["id"])).fetchone()
            if not source:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Задание не найдено")
                return
            now = int(time.time())
            cursor = database.execute(
                """INSERT INTO assignments(group_id, teacher_id, title, variant_id, tasks_json, due_at, created_at, updated_at, source_assignment_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (source["group_id"], user["id"], f"{source['title']} · повтор", source["variant_id"],
                 source["tasks_json"], source["due_at"], now, now, assignment_id),
            )
        self.send_json({"assignment": {"id": cursor.lastrowid}}, HTTPStatus.CREATED)

    def submission_create(self, assignment_id: int) -> None:
        user = self.require_role("student")
        if not user:
            return
        payload = self.read_json()
        if payload is None:
            return
        run = payload.get("run")
        if not isinstance(run, dict):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Некорректная попытка")
            return
        encoded_run = json.dumps(run, ensure_ascii=False, separators=(",", ":"))
        if len(encoded_run) > 100_000:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Данные попытки слишком велики")
            return
        with connect() as database:
            assignment = database.execute(
                """
                SELECT assignments.id FROM assignments
                JOIN group_members ON group_members.group_id = assignments.group_id
                WHERE assignments.id = ? AND group_members.user_id = ?
                """,
                (assignment_id, user["id"]),
            ).fetchone()
            if not assignment:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Задание не найдено")
                return
            attempt = database.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS number FROM submissions WHERE assignment_id = ? AND student_id = ?",
                (assignment_id, user["id"]),
            ).fetchone()["number"]
            cursor = database.execute(
                """
                INSERT INTO submissions(assignment_id, student_id, attempt_number, run_json, submitted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (assignment_id, user["id"], attempt, encoded_run, int(time.time())),
            )
            self.audit(
                database, "submission_created", user_id=user["id"], email=user["email"],
                details={"submissionId": cursor.lastrowid, "assignmentId": assignment_id, "attempt": attempt},
            )
        self.send_json({"submission": {"id": cursor.lastrowid, "attempt": attempt}}, HTTPStatus.CREATED)

    def recording_create(self, submission_id: int) -> None:
        user = self.require_role("student")
        if not user:
            return
        query = parse_qs(urlparse(self.path).query)
        try:
            task = int(query.get("task", [""])[0])
            question_value = query.get("question", [None])[0]
            question = int(question_value) if question_value else None
        except (TypeError, ValueError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Некорректный номер записи")
            return
        label = str(query.get("label", [f"Задание {task}"])[0])[:160]
        mime_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
        extensions = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav"}
        if task not in {1, 2, 3} or mime_type not in extensions:
            self.send_error_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Неподдерживаемый формат аудио")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_AUDIO_BODY:
            self.send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Запись превышает 15 МБ")
            return
        with connect() as database:
            row = database.execute(
                """
                SELECT submissions.id, assignments.tasks_json FROM submissions
                JOIN assignments ON assignments.id = submissions.assignment_id
                WHERE submissions.id = ? AND submissions.student_id = ?
                """,
                (submission_id, user["id"]),
            ).fetchone()
            if not row or task not in json.loads(row["tasks_json"]):
                self.send_error_json(HTTPStatus.FORBIDDEN, "Запись не относится к этой попытке")
                return
        data = self.rfile.read(length)
        relative = f"{submission_id}/{secrets.token_urlsafe(18)}.{extensions[mime_type]}"
        target = (AUDIO_DIR / relative).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        try:
            duration = validate_duration(target, task)
        except (OSError, ValueError, subprocess.SubprocessError):
            target.unlink(missing_ok=True)
            self.send_error_json(HTTPStatus.UNPROCESSABLE_ENTITY, "Некорректная или слишком длинная аудиозапись")
            return
        try:
            with connect() as database:
                cursor = database.execute(
                    """
                    INSERT INTO recordings(submission_id, task_number, question_number, label, file_name, mime_type, size_bytes, duration_seconds, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (submission_id, task, question, label, relative, mime_type, len(data), duration, int(time.time())),
                )
                self.audit(
                    database, "recording_uploaded", user_id=user["id"], email=user["email"],
                    details={"submissionId": submission_id, "task": task, "size": len(data)},
                )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        self.send_json({"recording": {"id": cursor.lastrowid}}, HTTPStatus.CREATED)

    def teacher_submissions(self) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        query = parse_qs(urlparse(self.path).query)
        try:
            group_id = int(query.get("group", [0])[0]) or None
        except ValueError:
            group_id = None
        student = str(query.get("student", [""])[0]).strip()
        status = str(query.get("status", [""])[0])
        with connect() as database:
            result = teacher_submissions(database, user["id"], group_id, student, status)
        self.send_json({"submissions": result})

    def submission_history(self, submission_id: int) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        with connect() as database:
            result = submission_history(database, user["id"], submission_id)
        if not result:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Работа не найдена")
            return
        self.send_json(result)

    def teacher_export(self, kind: str) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        query = parse_qs(urlparse(self.path).query)
        try:
            group_id = int(query.get("group", [0])[0]) or None
        except ValueError:
            group_id = None
        with connect() as database:
            items = teacher_submissions(
                database, user["id"], group_id, str(query.get("student", [""])[0]), str(query.get("status", [""])[0])
            )
        if kind == "csv":
            self.send_bytes(submissions_csv(items), "text/csv; charset=utf-8", "raboty-uchenikov.csv")
        else:
            self.send_bytes(submissions_pdf(items), "application/pdf", "raboty-uchenikov.pdf")

    def recording_get(self, recording_id: int) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        with connect() as database:
            row = database.execute(
                """
                SELECT recordings.file_name, recordings.mime_type, recordings.size_bytes,
                       submissions.student_id, assignments.teacher_id
                FROM recordings JOIN submissions ON submissions.id = recordings.submission_id
                JOIN assignments ON assignments.id = submissions.assignment_id
                WHERE recordings.id = ?
                """,
                (recording_id,),
            ).fetchone()
        if not row or user["id"] not in {row["student_id"], row["teacher_id"]}:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Запись не найдена")
            return
        audio_root = AUDIO_DIR.resolve()
        target = (audio_root / row["file_name"]).resolve()
        if audio_root not in target.parents or not target.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Файл записи не найден")
            return
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", row["mime_type"])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def review_submission(self, submission_id: int) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        payload = self.read_json()
        if payload is None:
            return
        comment = str(payload.get("comment", "")).strip()
        if len(comment) > 3000:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Комментарий слишком длинный")
            return
        with connect() as database:
            row = database.execute(
                """
                SELECT assignments.tasks_json FROM submissions
                JOIN assignments ON assignments.id = submissions.assignment_id
                WHERE submissions.id = ? AND assignments.teacher_id = ?
                """,
                (submission_id, user["id"]),
            ).fetchone()
            if not row:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Работа не найдена")
                return
            tasks = json.loads(row["tasks_json"])
            try:
                scores, total, maximum = validate_scores(payload.get("scores"), tasks)
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            now = int(time.time())
            database.execute(
                """
                INSERT INTO reviews(submission_id, teacher_id, scores_json, total_score, max_score, comment, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(submission_id) DO UPDATE SET scores_json = excluded.scores_json,
                    total_score = excluded.total_score, max_score = excluded.max_score,
                    comment = excluded.comment, reviewed_at = excluded.reviewed_at
                """,
                (submission_id, user["id"], json.dumps(scores), total, maximum, comment, now),
            )
            database.execute("UPDATE submissions SET status = 'graded' WHERE id = ?", (submission_id,))
            self.audit(
                database, "submission_reviewed", user_id=user["id"], email=user["email"],
                details={"submissionId": submission_id, "total": total, "maximum": maximum},
            )
        self.send_json({"review": {"total": total, "maximum": maximum}})

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
                SELECT users.id, users.email, users.display_name, users.role, users.email_verified_at FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_digest(token), int(time.time())),
            ).fetchone()
        return self.user_payload(
            row["id"], row["email"], row["display_name"], row["role"], row["email_verified_at"]
        ) if row else None

    @staticmethod
    def user_payload(
        user_id: int, email: str, display_name: str, role: str, email_verified_at: int | None
    ) -> dict:
        return {
            "id": user_id,
            "email": email,
            "displayName": display_name,
            "role": role,
            "emailVerified": email_verified_at is not None,
        }

    @staticmethod
    def user_for_token(database: sqlite3.Connection, token: str) -> sqlite3.Row | None:
        return database.execute(
            """
            SELECT users.id, users.email FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ?
            """,
            (token_digest(token),),
        ).fetchone()

    def audit(
        self,
        database: sqlite3.Connection,
        action: str,
        *,
        user_id: int | None = None,
        email: str | None = None,
        details: dict | None = None,
    ) -> None:
        record_audit(
            database,
            action,
            user_id=user_id,
            email=email,
            ip_address=self.client_address[0],
            user_agent=self.headers.get("User-Agent", ""),
            details=details,
        )

    def send_account_link(self, kind: str, email: str, token: str) -> str:
        public_url = os.environ.get("TRAINER_PUBLIC_URL", "").rstrip("/")
        if not public_url:
            origin = self.headers.get("Origin")
            public_url = origin.rstrip("/") if origin else f"http://{self.headers.get('Host', '127.0.0.1:8080')}"
        parameter = "verify" if kind == "email_verification" else "reset"
        url = f"{public_url}/?{parameter}={quote(token)}"
        if kind == "email_verification":
            subject = "Подтвердите email — тренажёр ЕГЭ"
            body = f"Подтвердите адрес электронной почты. Ссылка действует 24 часа:\n\n{url}"
        else:
            subject = "Восстановление пароля — тренажёр ЕГЭ"
            body = f"Создайте новый пароль. Ссылка действует 1 час:\n\n{url}"
        try:
            return send_email(DATA_DIR, email, subject, body)
        except Exception as error:
            with connect() as database:
                user = database.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                self.audit(
                    database, "email_delivery_failed", user_id=user["id"] if user else None,
                    email=email, details={"kind": kind},
                )
            print(f"Email delivery failed: {type(error).__name__}")
            return "failed"

    @staticmethod
    def delete_audio_files(file_names: list[str]) -> None:
        audio_root = AUDIO_DIR.resolve()
        for file_name in file_names:
            target = (audio_root / file_name).resolve()
            if audio_root not in target.parents:
                continue
            try:
                target.unlink(missing_ok=True)
            except OSError:
                continue
            try:
                target.parent.rmdir()
            except OSError:
                pass

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
        return request_has_same_origin(
            self.headers.get("Host"),
            self.headers.get("Origin"),
            self.headers.get("Referer"),
            self.headers.get("Sec-Fetch-Site"),
        )

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
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
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

    def send_bytes(self, data: bytes, content_type: str, filename: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(data)

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
