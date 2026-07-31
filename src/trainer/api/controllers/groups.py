from __future__ import annotations

import json
import secrets
import time
from http import HTTPStatus

from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import ActionResult, RequestContext
from trainer.api.runtime import GROUP_CODE_ALPHABET, connect
from trainer.api.schemas import GroupRequest, JoinGroupRequest, ProgressRequest
from trainer.infrastructure.database.core import INTEGRITY_ERRORS
from trainer.infrastructure.database.queries.groups import teacher_dashboard as fetch_teacher_dashboard
from trainer.services import accounts as account_services


def progress_get(user: dict) -> ActionResult:
    with connect() as database:
        row = database.execute(
            "SELECT progress_json, updated_at FROM user_progress WHERE user_id = ?", (user["id"],)
        ).fetchone()
    progress = json.loads(row["progress_json"]) if row else None
    return ActionResult({"progress": progress, "updatedAt": row["updated_at"] if row else None})


def progress_put(payload: ProgressRequest, user: dict) -> ActionResult:
    progress = payload.progress
    if not isinstance(progress, dict) or progress.get("version") != 1:
        raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), "Invalid progress document", HTTPStatus.BAD_REQUEST)
    runs = progress.get("runs", [])
    if not isinstance(runs, list) or len(runs) > 200:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Progress history is too large", HTTPStatus.BAD_REQUEST
        )
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
    return ActionResult({"ok": True, "updatedAt": now})


def teacher_group_create(payload: GroupRequest, user: dict, context: RequestContext) -> ActionResult:
    name = payload.name.strip()
    if not 2 <= len(name) <= 80:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST),
            "Название группы должно содержать от 2 до 80 символов",
            HTTPStatus.BAD_REQUEST,
        )
    cursor = None
    code = None
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
        raise ApiError(
            default_error_code(HTTPStatus.INTERNAL_SERVER_ERROR),
            "Не удалось создать код группы",
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    with connect() as database:
        account_services.audit(
            database,
            "group_created",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
            details={"groupId": cursor.lastrowid, "name": name},
        )
    return ActionResult({"group": {"id": cursor.lastrowid, "name": name, "code": code}}, status=HTTPStatus.CREATED)


def group_join(payload: JoinGroupRequest, user: dict, context: RequestContext) -> ActionResult:
    code = payload.code.strip().upper().replace(" ", "")
    with connect() as database:
        group = database.execute("SELECT id, name FROM study_groups WHERE join_code = ?", (code,)).fetchone()
        if not group:
            raise ApiError("group_not_found", "Группа с таким кодом не найдена", HTTPStatus.NOT_FOUND)
        database.execute(
            "INSERT OR IGNORE INTO group_members(group_id, user_id, joined_at) VALUES (?, ?, ?)",
            (group["id"], user["id"], int(time.time())),
        )
        account_services.audit(
            database,
            "group_joined",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
            details={"groupId": group["id"], "name": group["name"]},
        )
    return ActionResult({"group": {"id": group["id"], "name": group["name"]}})


def student_groups(user: dict) -> ActionResult:
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
    return ActionResult({"groups": [dict(row) for row in rows]})


def teacher_dashboard(user: dict) -> ActionResult:
    with connect() as database:
        result = fetch_teacher_dashboard(database, user["id"])
    return ActionResult({"groups": result})
