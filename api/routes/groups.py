from fastapi import APIRouter, Request

from api.http import invoke

router = APIRouter(prefix="/api")


@router.get("/progress")
async def get_progress(request: Request):
    return await invoke(request, "progress_get")


@router.put("/progress")
async def put_progress(request: Request):
    return await invoke(request, "progress_put")


@router.post("/teacher/groups")
async def create_group(request: Request):
    return await invoke(request, "teacher_group_create")


@router.post("/groups/join")
async def join_group(request: Request):
    return await invoke(request, "group_join")


@router.get("/student/groups")
async def student_groups(request: Request):
    return await invoke(request, "student_groups")


@router.get("/teacher/dashboard")
async def teacher_dashboard(request: Request):
    return await invoke(request, "teacher_dashboard")
