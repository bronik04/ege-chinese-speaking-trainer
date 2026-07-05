from __future__ import annotations

import json
import secrets
import time
from http import HTTPStatus

from api.runtime import GROUP_CODE_ALPHABET, connect
from backend.database import INTEGRITY_ERRORS
from backend.queries import teacher_dashboard


class GroupControllerMixin:
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
        cursor = None
        for _ in range(10):
            code = "".join(secrets.choice(GROUP_CODE_ALPHABET) for _ in range(6))
            try:
                with connect() as database:
                    cursor = database.execute(
                        "INSERT INTO study_groups(teacher_id, name, join_code, created_at) VALUES (?, ?, ?, ?)",
                        (user["id"], name, code, int(time.time())),
                    )
                break
            except INTEGRITY_ERRORS:
                continue
        if cursor is None:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Не удалось создать код группы")
            return
        with connect() as database:
            self.audit(
                database,
                "group_created",
                user_id=user["id"],
                email=user["email"],
                details={"groupId": cursor.lastrowid, "name": name},
            )
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
            group = database.execute("SELECT id, name FROM study_groups WHERE join_code = ?", (code,)).fetchone()
            if not group:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Группа с таким кодом не найдена")
                return
            database.execute(
                "INSERT OR IGNORE INTO group_members(group_id, user_id, joined_at) VALUES (?, ?, ?)",
                (group["id"], user["id"], int(time.time())),
            )
            self.audit(
                database,
                "group_joined",
                user_id=user["id"],
                email=user["email"],
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
