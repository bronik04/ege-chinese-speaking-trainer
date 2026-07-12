from __future__ import annotations

import json
import re
import time
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from trainer.api import runtime
from trainer.api.runtime import ROOT, connect
from trainer.domain.grading import validate_scores
from trainer.infrastructure.database.queries.assignments import student_assignments, teacher_assignments
from trainer.infrastructure.database.queries.submissions import submission_history, teacher_submissions
from trainer.infrastructure.database.submissions import create_submission_with_retry
from trainer.infrastructure.exports import submissions_csv, submissions_pdf
from trainer.infrastructure.storage import storage_from_env
from trainer.services.assignment_assets import copy_assignment_assets
from trainer.services.materials import assignment_material


class WorkControllerMixin:
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
                self.send_error_json(HTTPStatus.NOT_FOUND, "Группа не найдена", "group_not_found")
                return
            material = assignment_material(ROOT, database, variant_id)
            if not material or any(str(task) not in material.get("tasks", {}) for task in tasks):
                self.send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "Материал не найден или не содержит выбранные задания",
                    "invalid_assignment_material",
                )
                return
            cursor = database.execute(
                """
                INSERT INTO assignments(group_id, teacher_id, title, variant_id, tasks_json, due_at, created_at,
                                        updated_at, material_snapshot_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    user["id"],
                    title,
                    variant_id,
                    json.dumps(tasks),
                    due_at,
                    int(time.time()),
                    int(time.time()),
                    json.dumps(material, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            snapshot = copy_assignment_assets(
                database,
                cursor.lastrowid,
                material,
                storage_from_env(runtime.MATERIAL_ASSET_DIR),
                storage_from_env(runtime.ASSIGNMENT_ASSET_DIR),
            )
            database.execute(
                "UPDATE assignments SET material_snapshot_json=? WHERE id=?",
                (json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), cursor.lastrowid),
            )
            self.audit(
                database,
                "assignment_created",
                user_id=user["id"],
                email=user["email"],
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

    def assignment_asset_get(self, asset_id: int) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Изображение не найдено", "asset_not_found")
            return
        with connect() as database:
            row = database.execute(
                """SELECT assignment_material_assets.storage_key,assignment_material_assets.mime_type,
                          assignments.teacher_id,
                          EXISTS(SELECT 1 FROM group_members
                                 WHERE group_members.group_id=assignments.group_id
                                   AND group_members.user_id=?) AS is_member
                   FROM assignment_material_assets
                   JOIN assignments ON assignments.id=assignment_material_assets.assignment_id
                   WHERE assignment_material_assets.id=?""",
                (user["id"], asset_id),
            ).fetchone()
        if not row or (row["teacher_id"] != user["id"] and not row["is_member"]):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Изображение не найдено", "asset_not_found")
            return
        try:
            data = storage_from_env(runtime.ASSIGNMENT_ASSET_DIR).read(row["storage_key"])
        except (FileNotFoundError, OSError, ValueError):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Изображение не найдено", "asset_not_found")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", row["mime_type"])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

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
                self.send_error_json(HTTPStatus.NOT_FOUND, "Задание не найдено", "assignment_not_found")
                return
        self.send_json({"ok": True})

    def teacher_assignment_resend(self, assignment_id: int) -> None:
        user = self.require_role("teacher")
        if not user:
            return
        with connect() as database:
            source = database.execute(
                "SELECT * FROM assignments WHERE id = ? AND teacher_id = ?", (assignment_id, user["id"])
            ).fetchone()
            if not source:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Задание не найдено", "assignment_not_found")
                return
            now = int(time.time())
            cursor = database.execute(
                """INSERT INTO assignments(group_id, teacher_id, title, variant_id, tasks_json, due_at, created_at,
                                              updated_at, source_assignment_id, material_snapshot_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source["group_id"],
                    user["id"],
                    f"{source['title']} · повтор",
                    source["variant_id"],
                    source["tasks_json"],
                    source["due_at"],
                    now,
                    now,
                    assignment_id,
                    source["material_snapshot_json"],
                ),
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
                self.send_error_json(HTTPStatus.NOT_FOUND, "Задание не найдено", "assignment_not_found")
                return
            assignment_details = database.execute(
                "SELECT due_at FROM assignments WHERE id = ?", (assignment_id,)
            ).fetchone()
        submitted_at = int(time.time())
        try:
            submission_id, attempt = create_submission_with_retry(
                connect, assignment_id, user["id"], encoded_run, submitted_at
            )
        except RuntimeError:
            self.send_error_json(
                HTTPStatus.CONFLICT, "Не удалось создать попытку. Повторите запрос", "submission_conflict"
            )
            return
        late = bool(assignment_details["due_at"] is not None and submitted_at > assignment_details["due_at"])
        with connect() as database:
            self.audit(
                database,
                "submission_created",
                user_id=user["id"],
                email=user["email"],
                details={
                    "submissionId": submission_id,
                    "assignmentId": assignment_id,
                    "attempt": attempt,
                    "late": late,
                },
            )
        self.send_json({"submission": {"id": submission_id, "attempt": attempt, "late": late}}, HTTPStatus.CREATED)

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
            self.send_error_json(HTTPStatus.NOT_FOUND, "Работа не найдена", "submission_not_found")
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
                self.send_error_json(HTTPStatus.NOT_FOUND, "Работа не найдена", "submission_not_found")
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
                database,
                "submission_reviewed",
                user_id=user["id"],
                email=user["email"],
                details={"submissionId": submission_id, "total": total, "maximum": maximum},
            )
        self.send_json({"review": {"total": total, "maximum": maximum}})
