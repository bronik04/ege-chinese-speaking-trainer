from fastapi import APIRouter, Request

from trainer.api.http import invoke
from trainer.api.schemas import GroupRequest, JoinGroupRequest, ProgressRequest

router = APIRouter(prefix="/api")


@router.get("/progress")
async def get_progress(request: Request):
    return await invoke(request, "progress_get")


@router.put("/progress")
async def put_progress(request: Request, payload: ProgressRequest):
    return await invoke(request, "progress_put", payload=payload)


@router.post("/teacher/groups")
async def create_group(request: Request, payload: GroupRequest):
    return await invoke(request, "teacher_group_create", payload=payload)


@router.post("/groups/join")
async def join_group(request: Request, payload: JoinGroupRequest):
    return await invoke(request, "group_join", payload=payload)


@router.get("/student/groups")
async def student_groups(request: Request):
    return await invoke(request, "student_groups")


@router.get("/teacher/dashboard")
async def teacher_dashboard(request: Request):
    return await invoke(request, "teacher_dashboard")
