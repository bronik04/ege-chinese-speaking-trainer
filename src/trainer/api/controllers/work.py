from __future__ import annotations

import json
import re
import time
from http import HTTPStatus

from trainer.api import runtime
from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import ActionResult, FileResult, RequestContext
from trainer.api.runtime import ROOT, connect
from trainer.api.schemas import AssignmentRequest, AssignmentUpdateRequest, ReviewRequest, SubmissionRequest
from trainer.domain.grading import validate_scores
from trainer.infrastructure.database.queries.assignments import student_assignments as fetch_student_assignments
from trainer.infrastructure.database.queries.assignments import teacher_assignments as fetch_teacher_assignments
from trainer.infrastructure.database.queries.submissions import submission_history as fetch_submission_history
from trainer.infrastructure.database.queries.submissions import teacher_submissions as fetch_teacher_submissions
from trainer.infrastructure.database.submissions import create_submission_with_retry
from trainer.infrastructure.exports import submissions_csv, submissions_pdf
from trainer.services import accounts as account_services
from trainer.services.assignment_assets import copy_assignment_assets_from_env, delete_assignment_assets
from trainer.services.materials import assignment_material


def teacher_assignment_create(payload: AssignmentRequest, user: dict, context: RequestContext) -> ActionResult:
    try:
        group_id = int(payload.groupId)
    except (TypeError, ValueError):
        raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), "Выберите учебную группу", HTTPStatus.BAD_REQUEST)
    title = payload.title.strip()
    variant_id = payload.variantId.strip()
    raw_tasks = payload.tasks
    due_at = payload.dueAt
    if not 2 <= len(title) <= 100 or not re.fullmatch(r"[a-z0-9-]{3,50}", variant_id):
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Проверьте название и вариант", HTTPStatus.BAD_REQUEST
        )
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Выберите хотя бы одно задание", HTTPStatus.BAD_REQUEST
        )
    try:
        tasks = sorted(set(int(task) for task in raw_tasks))
        due_at = int(due_at) if due_at is not None else None
    except (TypeError, ValueError):
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Некорректные параметры задания", HTTPStatus.BAD_REQUEST
        )
    if any(task not in {1, 2, 3} for task in tasks):
        raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), "Допустимы задания 1–3", HTTPStatus.BAD_REQUEST)
    created_asset_keys: list[str] = []
    try:
        with connect() as database:
            group = database.execute(
                "SELECT id FROM study_groups WHERE id = ? AND teacher_id = ?", (group_id, user["id"])
            ).fetchone()
            if not group:
                raise ApiError("group_not_found", "Группа не найдена", HTTPStatus.NOT_FOUND)
            material = assignment_material(ROOT, database, variant_id)
            if not material or any(str(task) not in material.get("tasks", {}) for task in tasks):
                raise ApiError(
                    "invalid_assignment_material",
                    "Материал не найден или не содержит выбранные задания",
                    HTTPStatus.BAD_REQUEST,
                )
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
            snapshot = copy_assignment_assets_from_env(
                database,
                cursor.lastrowid,
                material,
                runtime.MATERIAL_ASSET_DIR,
                runtime.ASSIGNMENT_ASSET_DIR,
                created_asset_keys,
            )
            database.execute(
                "UPDATE assignments SET material_snapshot_json=? WHERE id=?",
                (json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), cursor.lastrowid),
            )
            account_services.audit(
                database,
                "assignment_created",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                user_id=user["id"],
                email=user["email"],
                details={"assignmentId": cursor.lastrowid, "groupId": group_id, "variantId": variant_id},
            )
    except ApiError:
        raise
    except Exception:
        if created_asset_keys:
            delete_assignment_assets(runtime.ASSIGNMENT_ASSET_DIR, created_asset_keys)
        raise
    return ActionResult({"assignment": {"id": cursor.lastrowid, "title": title}}, status=HTTPStatus.CREATED)


def student_assignments(user: dict) -> ActionResult:
    with connect() as database:
        result = fetch_student_assignments(database, user["id"])
    return ActionResult({"assignments": result})


def assignment_asset_get(asset_id: int, user: dict | None) -> FileResult:
    if not user:
        raise ApiError("asset_not_found", "Изображение не найдено", HTTPStatus.NOT_FOUND)
    with connect() as database:
        row = database.execute(
            """SELECT assignment_material_assets.storage_key,assignment_material_assets.mime_type,
                      assignment_material_assets.size_bytes,
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
        raise ApiError("asset_not_found", "Изображение не найдено", HTTPStatus.NOT_FOUND)
    return FileResult(key=row["storage_key"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])


def teacher_assignments(user: dict) -> ActionResult:
    with connect() as database:
        result = fetch_teacher_assignments(database, user["id"])
    return ActionResult({"assignments": result})


def teacher_assignment_update(assignment_id: int, payload: AssignmentUpdateRequest, user: dict) -> ActionResult:
    title = payload.title.strip()
    due_at = payload.dueAt
    if not 2 <= len(title) <= 100:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST),
            "Название должно содержать от 2 до 100 символов",
            HTTPStatus.BAD_REQUEST,
        )
    try:
        due_at = int(due_at) if due_at is not None else None
    except (TypeError, ValueError):
        raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), "Некорректный срок", HTTPStatus.BAD_REQUEST)
    with connect() as database:
        cursor = database.execute(
            "UPDATE assignments SET title = ?, due_at = ?, updated_at = ? WHERE id = ? AND teacher_id = ?",
            (title, due_at, int(time.time()), assignment_id, user["id"]),
        )
        if not cursor.rowcount:
            raise ApiError("assignment_not_found", "Задание не найдено", HTTPStatus.NOT_FOUND)
    return ActionResult({"ok": True})


def teacher_assignment_resend(assignment_id: int, user: dict, context: RequestContext) -> ActionResult:
    created_asset_keys: list[str] = []
    try:
        with connect() as database:
            source = database.execute(
                "SELECT * FROM assignments WHERE id = ? AND teacher_id = ?", (assignment_id, user["id"])
            ).fetchone()
            if not source:
                raise ApiError("assignment_not_found", "Задание не найдено", HTTPStatus.NOT_FOUND)
            if not source["material_snapshot_json"]:
                # Назначения, выданные до появления снимков, хранят NULL —
                # копировать нечего, и json.loads(None) уронил бы запрос в 500.
                raise ApiError(
                    "assignment_material_unavailable",
                    "У задания нет сохранённого материала; создайте новое назначение",
                    HTTPStatus.CONFLICT,
                )
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
            source_snapshot = json.loads(source["material_snapshot_json"])
            snapshot = copy_assignment_assets_from_env(
                database,
                cursor.lastrowid,
                source_snapshot,
                runtime.MATERIAL_ASSET_DIR,
                runtime.ASSIGNMENT_ASSET_DIR,
                created_asset_keys,
            )
            database.execute(
                "UPDATE assignments SET material_snapshot_json=? WHERE id=?",
                (json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), cursor.lastrowid),
            )
    except ApiError:
        raise
    except Exception:
        # Транзакция откатилась, поэтому скопированные файлы уже никем
        # не адресуются — убираем их, чтобы не копить осиротевшие объекты.
        if created_asset_keys:
            delete_assignment_assets(runtime.ASSIGNMENT_ASSET_DIR, created_asset_keys)
        raise
    return ActionResult({"assignment": {"id": cursor.lastrowid}}, status=HTTPStatus.CREATED)


def submission_create(
    assignment_id: int, payload: SubmissionRequest, user: dict, context: RequestContext
) -> ActionResult:
    run = payload.run
    if not isinstance(run, dict):
        raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), "Некорректная попытка", HTTPStatus.BAD_REQUEST)
    encoded_run = json.dumps(run, ensure_ascii=False, separators=(",", ":"))
    if len(encoded_run) > 100_000:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Данные попытки слишком велики", HTTPStatus.BAD_REQUEST
        )
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
            raise ApiError("assignment_not_found", "Задание не найдено", HTTPStatus.NOT_FOUND)
        assignment_details = database.execute(
            "SELECT due_at FROM assignments WHERE id = ?", (assignment_id,)
        ).fetchone()
    submitted_at = int(time.time())
    try:
        submission_id, attempt = create_submission_with_retry(
            connect, assignment_id, user["id"], encoded_run, submitted_at
        )
    except RuntimeError:
        raise ApiError("submission_conflict", "Не удалось создать попытку. Повторите запрос", HTTPStatus.CONFLICT)
    late = bool(assignment_details["due_at"] is not None and submitted_at > assignment_details["due_at"])
    with connect() as database:
        account_services.audit(
            database,
            "submission_created",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
            details={
                "submissionId": submission_id,
                "assignmentId": assignment_id,
                "attempt": attempt,
                "late": late,
            },
        )
    return ActionResult(
        {"submission": {"id": submission_id, "attempt": attempt, "late": late}}, status=HTTPStatus.CREATED
    )


def teacher_submissions(query: dict, user: dict) -> ActionResult:
    try:
        group_id = int(query.get("group") or 0) or None
    except ValueError:
        group_id = None
    student = str(query.get("student") or "").strip()
    status = str(query.get("status") or "")
    with connect() as database:
        result = fetch_teacher_submissions(database, user["id"], group_id, student, status)
    return ActionResult({"submissions": result})


def submission_history(submission_id: int, user: dict) -> ActionResult:
    with connect() as database:
        result = fetch_submission_history(database, user["id"], submission_id)
    if not result:
        raise ApiError("submission_not_found", "Работа не найдена", HTTPStatus.NOT_FOUND)
    return ActionResult(result)


def teacher_export(fmt: str, query: dict, user: dict) -> tuple[bytes, str, str]:
    try:
        group_id = int(query.get("group", 0)) or None
    except ValueError:
        group_id = None
    with connect() as database:
        items = fetch_teacher_submissions(
            database, user["id"], group_id, str(query.get("student", "")), str(query.get("status", ""))
        )
    if fmt == "csv":
        return submissions_csv(items), "text/csv; charset=utf-8", "raboty-uchenikov.csv"
    return submissions_pdf(items), "application/pdf", "raboty-uchenikov.pdf"


def review_submission(submission_id: int, payload: ReviewRequest, user: dict, context: RequestContext) -> ActionResult:
    comment = payload.comment.strip()
    if len(comment) > 3000:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Комментарий слишком длинный", HTTPStatus.BAD_REQUEST
        )
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
            raise ApiError("submission_not_found", "Работа не найдена", HTTPStatus.NOT_FOUND)
        tasks = json.loads(row["tasks_json"])
        try:
            scores, total, maximum = validate_scores(payload.scores, tasks)
        except ValueError as error:
            raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), str(error), HTTPStatus.BAD_REQUEST) from error
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
        account_services.audit(
            database,
            "submission_reviewed",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
            details={"submissionId": submission_id, "total": total, "maximum": maximum},
        )
    return ActionResult({"review": {"total": total, "maximum": maximum}})
