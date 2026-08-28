from __future__ import annotations

import json
import secrets
import subprocess
import tempfile
import time
from contextlib import suppress
from http import HTTPStatus
from pathlib import Path

from trainer.api import runtime
from trainer.api.dependencies import owner_email_from_env
from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import ActionResult, RequestContext
from trainer.api.schemas import ReviewRequestCreate, ReviewScoresRequest
from trainer.domain.grading import CRITERIA, validate_scores
from trainer.domain.recording_retention import expires_at
from trainer.domain.review_requests import required_recording_positions, validate_review_selection
from trainer.infrastructure.audio import validate_duration
from trainer.infrastructure.database.core import begin_immediate
from trainer.infrastructure.database.queries.review_requests import (
    review_request_detail as fetch_review_request_detail,
)
from trainer.infrastructure.database.queries.review_requests import (
    student_review_requests as fetch_student_review_requests,
)
from trainer.infrastructure.database.queries.review_requests import (
    teacher_review_requests as fetch_teacher_review_requests,
)
from trainer.services import accounts as account_services
from trainer.services.materials import assignment_material
from trainer.services.recordings import write_recording
from trainer.services.review_assets import copy_review_assets_from_env
from trainer.services.storage_cleanup import enqueue_cleanup_job, process_cleanup_jobs


def _validation_error(error: ValueError) -> ApiError:
    return ApiError(default_error_code(HTTPStatus.BAD_REQUEST), str(error), HTTPStatus.BAD_REQUEST)


def _owner_allowed(user: dict) -> bool:
    return bool(
        user.get("role") == "teacher"
        and user.get("emailVerified")
        and str(user.get("email", "")).strip().lower() == owner_email_from_env()
    )


def _cleanup_orphaned(*, audio_keys: list[str] | None = None, assignment_keys: list[str] | None = None) -> None:
    audio_keys = audio_keys or []
    assignment_keys = assignment_keys or []
    if not audio_keys and not assignment_keys:
        return
    with suppress(Exception):
        with runtime.connect() as database:
            enqueue_cleanup_job(
                database,
                audio_keys=audio_keys,
                material_keys=[],
                assignment_keys=assignment_keys,
            )
        with runtime.connect() as database:
            process_cleanup_jobs(
                database,
                audio_root=runtime.AUDIO_DIR,
                material_root=runtime.MATERIAL_ASSET_DIR,
                assignment_root=runtime.ASSIGNMENT_ASSET_DIR,
            )


def review_request_create(payload: ReviewRequestCreate, user: dict, context: RequestContext) -> ActionResult:
    try:
        selection = validate_review_selection(payload.kind, payload.tasks)
    except ValueError as error:
        raise _validation_error(error) from error
    variant_id = payload.variantId.strip()
    encoded_run = json.dumps(payload.run, ensure_ascii=False, separators=(",", ":"))
    if len(encoded_run.encode("utf-8")) > 100_000:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Данные попытки слишком велики", HTTPStatus.BAD_REQUEST
        )

    created_asset_keys: list[str] = []
    try:
        with runtime.connect() as database:
            material = assignment_material(runtime.ROOT, database, variant_id)
            material_tasks = material.get("tasks", {}) if isinstance(material, dict) else {}
            if not material or any(str(task) not in material_tasks for task in selection.tasks):
                raise ApiError(
                    "invalid_review_material",
                    "Материал не найден или не содержит выбранные задания",
                    HTTPStatus.BAD_REQUEST,
                )
            trimmed_material = {
                **material,
                "tasks": {str(task): material_tasks[str(task)] for task in selection.tasks},
            }
            cursor = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json)
                   VALUES (?,?,?,?,?)""",
                (user["id"], selection.kind, "uploading", variant_id, encoded_run),
            )
            request_id = cursor.lastrowid
            snapshot = copy_review_assets_from_env(database, request_id, trimmed_material, created_asset_keys)
            for task in selection.tasks:
                database.execute(
                    """INSERT INTO review_request_items(request_id,task_number,task_snapshot_json)
                       VALUES (?,?,?)""",
                    (
                        request_id,
                        task,
                        json.dumps(snapshot["tasks"][str(task)], ensure_ascii=False, separators=(",", ":")),
                    ),
                )
            account_services.audit(
                database,
                "review_request_created",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                user_id=user["id"],
                email=user["email"],
                details={"requestId": request_id, "tasks": list(selection.tasks)},
            )
    except ApiError:
        _cleanup_orphaned(assignment_keys=created_asset_keys)
        raise
    except Exception:
        _cleanup_orphaned(assignment_keys=created_asset_keys)
        raise
    return ActionResult(
        {"reviewRequest": {"id": request_id, "status": "uploading"}},
        status=HTTPStatus.CREATED,
    )


def review_recording_create(
    request_id: int,
    query: dict,
    body: bytes,
    content_type: str,
    user: dict,
    context: RequestContext,
) -> ActionResult:
    try:
        task = int(query.get("task") or "")
        question_value = query.get("question")
        question = int(question_value) if question_value else None
    except (TypeError, ValueError) as error:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Некорректный номер записи", HTTPStatus.BAD_REQUEST
        ) from error
    label = str(query.get("label") or f"Задание {task}")[:160]
    mime_type = content_type.split(";", 1)[0].lower()
    extensions = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav"}
    if task not in {1, 2, 3} or mime_type not in extensions:
        raise ApiError(
            default_error_code(HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
            "Неподдерживаемый формат аудио",
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        )
    if (task == 1 and question not in {1, 2, 3, 4, 5}) or (task in {2, 3} and question is not None):
        raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), "Некорректный номер записи", HTTPStatus.BAD_REQUEST)
    if not 0 < len(body) <= runtime.MAX_AUDIO_BODY:
        raise ApiError(
            default_error_code(HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
            "Запись превышает 15 МБ",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    with runtime.connect() as database:
        item = database.execute(
            """SELECT review_request_items.id,review_requests.status
               FROM review_request_items
               JOIN review_requests ON review_requests.id=review_request_items.request_id
               WHERE review_requests.id=? AND review_requests.student_id=? AND review_request_items.task_number=?""",
            (request_id, user["id"], task),
        ).fetchone()
    if not item:
        raise ApiError("review_request_not_found", "Запрос не найден", HTTPStatus.NOT_FOUND)
    if item["status"] != "uploading":
        raise ApiError("review_request_not_uploading", "Запрос уже отправлен", HTTPStatus.CONFLICT)

    storage_key = f"review-requests/{request_id}/{secrets.token_urlsafe(18)}.{extensions[mime_type]}"
    temporary_dir = runtime.DATA_DIR / "tmp"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=temporary_dir, suffix=f".{extensions[mime_type]}", delete=False) as file:
        file.write(body)
        temporary_path = Path(file.name)
    try:
        duration = validate_duration(temporary_path, task)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        temporary_path.unlink(missing_ok=True)
        raise ApiError(
            default_error_code(HTTPStatus.UNPROCESSABLE_ENTITY),
            "Некорректная или слишком длинная аудиозапись",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        ) from error
    try:
        write_recording(runtime.AUDIO_DIR, storage_key, temporary_path, mime_type)
        with runtime.connect() as database:
            begin_immediate(database)
            current = database.execute(
                """SELECT review_request_items.id,review_requests.status
                   FROM review_request_items
                   JOIN review_requests ON review_requests.id=review_request_items.request_id
                   WHERE review_requests.id=? AND review_requests.student_id=? AND review_request_items.task_number=?""",
                (request_id, user["id"], task),
            ).fetchone()
            if not current:
                raise ApiError("review_request_not_found", "Запрос не найден", HTTPStatus.NOT_FOUND)
            if current["status"] != "uploading":
                raise ApiError("review_request_not_uploading", "Запрос уже отправлен", HTTPStatus.CONFLICT)
            guarded = database.execute(
                """UPDATE review_requests SET status='uploading'
                   WHERE id=? AND student_id=? AND status='uploading'""",
                (request_id, user["id"]),
            )
            if not guarded.rowcount:
                raise ApiError("review_request_not_uploading", "Запрос уже отправлен", HTTPStatus.CONFLICT)
            replaced = database.execute(
                """SELECT storage_key FROM review_request_recordings
                   WHERE item_id=? AND question_number IS ?""",
                (current["id"], question),
            ).fetchall()
            if replaced:
                database.execute(
                    "DELETE FROM review_request_recordings WHERE item_id=? AND question_number IS ?",
                    (current["id"], question),
                )
            created_at = int(time.time())
            cursor = database.execute(
                """INSERT INTO review_request_recordings
                   (item_id,question_number,label,storage_key,mime_type,size_bytes,duration_seconds,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    current["id"],
                    question,
                    label,
                    storage_key,
                    mime_type,
                    len(body),
                    duration,
                    created_at,
                    expires_at(created_at),
                ),
            )
            if replaced:
                enqueue_cleanup_job(
                    database,
                    audio_keys=[row["storage_key"] for row in replaced],
                    material_keys=[],
                    assignment_keys=[],
                )
            account_services.audit(
                database,
                "review_recording_uploaded",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                user_id=user["id"],
                email=user["email"],
                details={"requestId": request_id, "task": task, "size": len(body)},
            )
    except Exception:
        _cleanup_orphaned(audio_keys=[storage_key])
        raise
    finally:
        temporary_path.unlink(missing_ok=True)
    return ActionResult({"recording": {"id": cursor.lastrowid}}, status=HTTPStatus.CREATED)


def review_request_complete(request_id: int, user: dict, context: RequestContext) -> ActionResult:
    with runtime.connect() as database:
        begin_immediate(database)
        request_row = database.execute(
            "SELECT status FROM review_requests WHERE id=? AND student_id=?",
            (request_id, user["id"]),
        ).fetchone()
        if not request_row:
            raise ApiError("review_request_not_found", "Запрос не найден", HTTPStatus.NOT_FOUND)
        if request_row["status"] != "uploading":
            raise ApiError("review_request_not_uploading", "Запрос уже отправлен", HTTPStatus.CONFLICT)
        items = database.execute(
            "SELECT id,task_number FROM review_request_items WHERE request_id=? ORDER BY task_number",
            (request_id,),
        ).fetchall()
        tasks = [row["task_number"] for row in items]
        recordings = database.execute(
            """SELECT review_request_items.task_number,review_request_recordings.question_number
               FROM review_request_recordings
               JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
               WHERE review_request_items.request_id=?""",
            (request_id,),
        ).fetchall()
        uploaded = {(row["task_number"], row["question_number"]) for row in recordings}
        missing = sorted(required_recording_positions(tasks) - uploaded, key=lambda item: (item[0], item[1] or 0))
        if missing:
            raise ApiError(
                "review_request_incomplete",
                "Загрузите все обязательные записи",
                HTTPStatus.CONFLICT,
                missing=[
                    {"task": task, **({"question": question} if question is not None else {})}
                    for task, question in missing
                ],
            )
        submitted_at = int(time.time())
        cursor = database.execute(
            """UPDATE review_requests SET status='queued',submitted_at=?
               WHERE id=? AND student_id=? AND status='uploading'""",
            (submitted_at, request_id, user["id"]),
        )
        if not cursor.rowcount:
            raise ApiError("review_request_not_uploading", "Запрос уже отправлен", HTTPStatus.CONFLICT)
        account_services.audit(
            database,
            "review_request_queued",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
            details={"requestId": request_id, "tasks": tasks},
        )
    return ActionResult({"reviewRequest": {"id": request_id, "status": "queued"}})


def review_request_discard(request_id: int, user: dict, context: RequestContext) -> ActionResult:
    with runtime.connect() as database:
        begin_immediate(database)
        request_row = database.execute(
            "SELECT status FROM review_requests WHERE id=? AND student_id=?",
            (request_id, user["id"]),
        ).fetchone()
        if not request_row:
            raise ApiError("review_request_not_found", "Запрос не найден", HTTPStatus.NOT_FOUND)
        if request_row["status"] != "uploading":
            raise ApiError("review_request_not_uploading", "Запрос уже отправлен", HTTPStatus.CONFLICT)
        audio_keys = [
            row["storage_key"]
            for row in database.execute(
                """SELECT review_request_recordings.storage_key FROM review_request_recordings
                   JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
                   WHERE review_request_items.request_id=?""",
                (request_id,),
            ).fetchall()
        ]
        asset_keys = [
            row["storage_key"]
            for row in database.execute(
                "SELECT storage_key FROM review_request_assets WHERE request_id=?", (request_id,)
            ).fetchall()
        ]
        database.execute("DELETE FROM review_requests WHERE id=? AND student_id=?", (request_id, user["id"]))
        if audio_keys or asset_keys:
            enqueue_cleanup_job(
                database,
                audio_keys=audio_keys,
                material_keys=[],
                assignment_keys=asset_keys,
            )
        account_services.audit(
            database,
            "review_request_discarded",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
            details={"requestId": request_id},
        )
    with suppress(Exception):
        with runtime.connect() as database:
            process_cleanup_jobs(
                database,
                audio_root=runtime.AUDIO_DIR,
                material_root=runtime.MATERIAL_ASSET_DIR,
                assignment_root=runtime.ASSIGNMENT_ASSET_DIR,
            )
    return ActionResult({"ok": True})


def student_review_requests(user: dict) -> ActionResult:
    with runtime.connect() as database:
        requests = fetch_student_review_requests(database, user["id"])
    for request in requests:
        if request["status"] != "reviewed":
            request.pop("total", None)
            request.pop("maximum", None)
    return ActionResult({"requests": requests})


def teacher_review_requests(query: dict) -> ActionResult:
    try:
        task = int(query.get("task") or 0) or None
    except (TypeError, ValueError):
        task = None
    try:
        submitted_from = int(query.get("submittedFrom")) if query.get("submittedFrom") is not None else None
        submitted_before = int(query.get("submittedBefore")) if query.get("submittedBefore") is not None else None
    except (TypeError, ValueError):
        submitted_from = submitted_before = None
    with runtime.connect() as database:
        requests = fetch_teacher_review_requests(
            database,
            student=str(query.get("student") or "").strip(),
            task=task,
            status=str(query.get("status") or "").strip(),
            submitted_from=submitted_from,
            submitted_before=submitted_before,
        )
    return ActionResult({"requests": requests})


def teacher_review_request_detail(request_id: int, user: dict) -> ActionResult:
    if not _owner_allowed(user):
        raise ApiError("review_request_not_found", "Запрос не найден", HTTPStatus.NOT_FOUND)
    with runtime.connect() as database:
        result = fetch_review_request_detail(database, request_id)
    if not result:
        raise ApiError("review_request_not_found", "Запрос не найден", HTTPStatus.NOT_FOUND)
    return ActionResult({"reviewRequest": result})


def teacher_review_request_score(
    request_id: int,
    payload: ReviewScoresRequest,
    user: dict,
    context: RequestContext,
) -> ActionResult:
    with runtime.connect() as database:
        request_row = database.execute(
            "SELECT status FROM review_requests WHERE id=? AND status IN ('queued','reviewed')",
            (request_id,),
        ).fetchone()
        if not request_row:
            raise ApiError("review_request_not_found", "Запрос не найден", HTTPStatus.NOT_FOUND)
        items = database.execute(
            "SELECT id,task_number FROM review_request_items WHERE request_id=? ORDER BY task_number",
            (request_id,),
        ).fetchall()
        tasks = [row["task_number"] for row in items]
        try:
            scores, total, maximum = validate_scores(payload.scores, tasks)
        except ValueError as error:
            raise _validation_error(error) from error
        for item in items:
            task = item["task_number"]
            task_scores = scores[str(task)]
            database.execute(
                """UPDATE review_request_items
                   SET scores_json=?,total_score=?,max_score=? WHERE id=?""",
                (
                    json.dumps(task_scores, ensure_ascii=False, separators=(",", ":")),
                    sum(task_scores.values()),
                    sum(CRITERIA[task].values()),
                    item["id"],
                ),
            )
        reviewed_at = int(time.time())
        database.execute(
            """UPDATE review_requests
               SET status='reviewed',reviewed_at=?,reviewer_id=? WHERE id=?""",
            (reviewed_at, user["id"], request_id),
        )
        account_services.audit(
            database,
            "review_request_scored",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
            details={"requestId": request_id, "tasks": tasks, "total": total, "maximum": maximum},
        )
    return ActionResult(
        {
            "reviewRequest": {
                "id": request_id,
                "status": "reviewed",
                "total": total,
                "maximum": maximum,
            }
        }
    )
