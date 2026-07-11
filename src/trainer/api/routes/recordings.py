from fastapi import APIRouter, Request

from trainer.api.http import invoke

router = APIRouter(prefix="/api")


@router.post("/submissions/{submission_id}/recordings")
async def create_recording(request: Request, submission_id: int):
    return await invoke(request, "recording_create", submission_id)


@router.get("/recordings/{recording_id}")
async def get_recording(request: Request, recording_id: int):
    return await invoke(request, "recording_get", recording_id)
