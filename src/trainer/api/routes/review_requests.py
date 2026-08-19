from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from trainer.api.controllers import review_requests as actions
from trainer.api.dependencies import request_context, require_authenticated, require_student, require_teacher
from trainer.api.routes import respond
from trainer.api.schemas import ReviewRequestCreate, ReviewScoresRequest

router = APIRouter(prefix="/api")


@router.post("/review-requests")
async def create_review_request(
    request: Request,
    payload: ReviewRequestCreate,
    user: dict = Depends(require_student),
):
    result = await run_in_threadpool(actions.review_request_create, payload, user, request_context(request))
    return respond(result)


@router.post("/review-requests/{request_id}/recordings")
async def create_review_recording(
    request: Request,
    request_id: int,
    task: str | None = None,
    question: str | None = None,
    label: str | None = None,
    user: dict = Depends(require_student),
):
    body = await request.body()
    result = await run_in_threadpool(
        actions.review_recording_create,
        request_id,
        {"task": task, "question": question, "label": label},
        body,
        request.headers.get("Content-Type", ""),
        user,
        request_context(request),
    )
    return respond(result)


@router.post("/review-requests/{request_id}/complete")
async def complete_review_request(
    request: Request,
    request_id: int,
    user: dict = Depends(require_student),
):
    result = await run_in_threadpool(actions.review_request_complete, request_id, user, request_context(request))
    return respond(result)


@router.get("/student/review-requests")
async def student_review_requests(user: dict = Depends(require_student)):
    result = await run_in_threadpool(actions.student_review_requests, user)
    return respond(result)


@router.get("/teacher/review-requests")
async def teacher_review_requests(
    student: str | None = None,
    task: str | None = None,
    status: str | None = None,
    _: dict = Depends(require_teacher),
):
    result = await run_in_threadpool(
        actions.teacher_review_requests,
        {"student": student, "task": task, "status": status},
    )
    return respond(result)


@router.get("/teacher/review-requests/{request_id}")
async def teacher_review_request_detail(
    request_id: int,
    user: dict = Depends(require_authenticated),
):
    result = await run_in_threadpool(actions.teacher_review_request_detail, request_id, user)
    return respond(result)


@router.put("/teacher/review-requests/{request_id}/scores")
async def score_review_request(
    request: Request,
    request_id: int,
    payload: ReviewScoresRequest,
    user: dict = Depends(require_teacher),
):
    result = await run_in_threadpool(
        actions.teacher_review_request_score,
        request_id,
        payload,
        user,
        request_context(request),
    )
    return respond(result)
