from http import HTTPStatus

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from trainer.api import runtime
from trainer.api.controllers import work as actions
from trainer.api.dependencies import current_user_or_none, request_context, require_student, require_teacher
from trainer.api.errors import ApiError
from trainer.api.routes import respond
from trainer.api.schemas import AssignmentRequest, AssignmentUpdateRequest, ReviewRequest, SubmissionRequest
from trainer.services.assignment_assets import read_assignment_asset

router = APIRouter(prefix="/api")


@router.get("/student/assignments")
async def student_assignments(user: dict = Depends(require_student)):
    result = await run_in_threadpool(actions.student_assignments, user)
    return respond(result)


@router.get("/assignment-assets/{asset_id}")
async def assignment_asset(asset_id: int, user: dict | None = Depends(current_user_or_none)):
    # Временная реализация до задачи 14: читает файл целиком в маршруте.
    # file_response() из задачи 14 заменит это на FileResponse с поддержкой Range.
    stored = await run_in_threadpool(actions.assignment_asset_get, asset_id, user)
    try:
        data = await run_in_threadpool(read_assignment_asset, runtime.ASSIGNMENT_ASSET_DIR, stored.key)
    except (FileNotFoundError, OSError, ValueError):
        raise ApiError("asset_not_found", "Изображение не найдено", HTTPStatus.NOT_FOUND) from None
    return Response(
        content=data,
        media_type=stored.mime_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/teacher/assignments")
async def teacher_assignments(user: dict = Depends(require_teacher)):
    result = await run_in_threadpool(actions.teacher_assignments, user)
    return respond(result)


@router.post("/teacher/assignments")
async def create_assignment(request: Request, payload: AssignmentRequest, user: dict = Depends(require_teacher)):
    result = await run_in_threadpool(actions.teacher_assignment_create, payload, user, request_context(request))
    return respond(result)


@router.put("/teacher/assignments/{assignment_id}")
async def update_assignment(
    assignment_id: int, payload: AssignmentUpdateRequest, user: dict = Depends(require_teacher)
):
    result = await run_in_threadpool(actions.teacher_assignment_update, assignment_id, payload, user)
    return respond(result)


@router.post("/teacher/assignments/{assignment_id}/resend")
async def resend_assignment(request: Request, assignment_id: int, user: dict = Depends(require_teacher)):
    result = await run_in_threadpool(actions.teacher_assignment_resend, assignment_id, user, request_context(request))
    return respond(result)


@router.post("/assignments/{assignment_id}/submissions")
async def create_submission(
    request: Request, assignment_id: int, payload: SubmissionRequest, user: dict = Depends(require_student)
):
    result = await run_in_threadpool(actions.submission_create, assignment_id, payload, user, request_context(request))
    return respond(result)


@router.get("/teacher/submissions")
async def teacher_submissions(
    group: str | None = None,
    student: str | None = None,
    status: str | None = None,
    user: dict = Depends(require_teacher),
):
    query = {"group": group, "student": student, "status": status}
    result = await run_in_threadpool(actions.teacher_submissions, query, user)
    return respond(result)


@router.get("/teacher/submissions/{submission_id}")
async def submission_history(submission_id: int, user: dict = Depends(require_teacher)):
    result = await run_in_threadpool(actions.submission_history, submission_id, user)
    return respond(result)


@router.get("/teacher/export.csv")
async def export_csv(request: Request, user: dict = Depends(require_teacher)):
    data, content_type, filename = await run_in_threadpool(
        actions.teacher_export, "csv", dict(request.query_params), user
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


@router.get("/teacher/export.pdf")
async def export_pdf(request: Request, user: dict = Depends(require_teacher)):
    data, content_type, filename = await run_in_threadpool(
        actions.teacher_export, "pdf", dict(request.query_params), user
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


@router.post("/submissions/{submission_id}/review")
async def review_submission(
    request: Request, submission_id: int, payload: ReviewRequest, user: dict = Depends(require_teacher)
):
    result = await run_in_threadpool(actions.review_submission, submission_id, payload, user, request_context(request))
    return respond(result)
