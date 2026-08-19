from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from trainer.api.controllers import recordings as actions
from trainer.api.dependencies import request_context, require_authenticated, require_student
from trainer.api.routes import file_response, respond

router = APIRouter(prefix="/api")


@router.post("/submissions/{submission_id}/recordings")
async def create_recording(
    request: Request,
    submission_id: int,
    task: str | None = None,
    question: str | None = None,
    label: str | None = None,
    user: dict = Depends(require_student),
):
    body = await request.body()
    result = await run_in_threadpool(
        actions.recording_create,
        submission_id,
        {"task": task, "question": question, "label": label},
        body,
        request.headers.get("Content-Type", ""),
        user,
        request_context(request),
    )
    return respond(result)


@router.get("/recordings/{recording_id}")
async def get_recording(
    recording_id: int,
    request: Request,
    user: dict = Depends(require_authenticated),
):
    stored = await run_in_threadpool(actions.recording_get, recording_id, user)
    range_headers = request.headers.getlist("Range")
    return file_response(
        stored,
        range_headers[0] if range_headers else None,
        range_header_count=len(range_headers),
    )
