from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from trainer.api.controllers import progress as actions
from trainer.api.dependencies import require_student
from trainer.api.routes import respond
from trainer.api.schemas import ProgressRequest

router = APIRouter(prefix="/api")


@router.get("/progress")
async def get_progress(user: dict = Depends(require_student)):
    result = await run_in_threadpool(actions.progress_get, user)
    return respond(result)


@router.put("/progress")
async def put_progress(payload: ProgressRequest, user: dict = Depends(require_student)):
    result = await run_in_threadpool(actions.progress_put, payload, user)
    return respond(result)
