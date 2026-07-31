from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from trainer.api.controllers import groups as actions
from trainer.api.dependencies import request_context, require_student, require_teacher
from trainer.api.routes import respond
from trainer.api.schemas import GroupRequest, JoinGroupRequest, ProgressRequest

router = APIRouter(prefix="/api")


@router.get("/progress")
async def get_progress(user: dict = Depends(require_student)):
    result = await run_in_threadpool(actions.progress_get, user)
    return respond(result)


@router.put("/progress")
async def put_progress(payload: ProgressRequest, user: dict = Depends(require_student)):
    result = await run_in_threadpool(actions.progress_put, payload, user)
    return respond(result)


@router.post("/teacher/groups")
async def create_group(request: Request, payload: GroupRequest, user: dict = Depends(require_teacher)):
    result = await run_in_threadpool(actions.teacher_group_create, payload, user, request_context(request))
    return respond(result)


@router.post("/groups/join")
async def join_group(request: Request, payload: JoinGroupRequest, user: dict = Depends(require_student)):
    result = await run_in_threadpool(actions.group_join, payload, user, request_context(request))
    return respond(result)


@router.get("/student/groups")
async def student_groups(user: dict = Depends(require_student)):
    result = await run_in_threadpool(actions.student_groups, user)
    return respond(result)


@router.get("/teacher/dashboard")
async def teacher_dashboard(user: dict = Depends(require_teacher)):
    result = await run_in_threadpool(actions.teacher_dashboard, user)
    return respond(result)
