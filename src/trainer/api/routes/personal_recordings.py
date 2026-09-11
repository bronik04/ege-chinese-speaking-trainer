from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from trainer.api.controllers import personal_recordings as actions
from trainer.api.dependencies import request_context, require_authenticated
from trainer.api.routes import file_response, respond
from trainer.api.schemas import PersonalRecordingUpload

router = APIRouter(prefix="/api")


@router.post("/personal-recordings")
async def create_personal_recording(
    request: Request,
    payload: PersonalRecordingUpload = Depends(),
    user: dict = Depends(require_authenticated),
):
    result = await run_in_threadpool(
        actions.personal_recording_create,
        payload,
        await request.body(),
        request.headers.get("Content-Type", ""),
        user,
        request_context(request),
    )
    return respond(result)


@router.get("/personal-recordings")
async def list_personal_recordings(user: dict = Depends(require_authenticated)):
    return respond(await run_in_threadpool(actions.personal_recordings_list, user))


@router.get("/personal-recordings/{recording_id}")
async def get_personal_recording(
    recording_id: int,
    request: Request,
    user: dict = Depends(require_authenticated),
):
    stored = await run_in_threadpool(actions.personal_recording_get, recording_id, user)
    range_headers = request.headers.getlist("Range")
    return file_response(stored, range_headers[0] if range_headers else None, range_header_count=len(range_headers))
