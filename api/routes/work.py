from fastapi import APIRouter, Request

from api.http import invoke

router = APIRouter(prefix="/api")


@router.get("/student/assignments")
async def student_assignments(request: Request):
    return await invoke(request, "student_assignments")


@router.get("/teacher/assignments")
async def teacher_assignments(request: Request):
    return await invoke(request, "teacher_assignments")


@router.post("/teacher/assignments")
async def create_assignment(request: Request):
    return await invoke(request, "teacher_assignment_create")


@router.put("/teacher/assignments/{assignment_id}")
async def update_assignment(request: Request, assignment_id: int):
    return await invoke(request, "teacher_assignment_update", assignment_id)


@router.post("/teacher/assignments/{assignment_id}/resend")
async def resend_assignment(request: Request, assignment_id: int):
    return await invoke(request, "teacher_assignment_resend", assignment_id)


@router.post("/assignments/{assignment_id}/submissions")
async def create_submission(request: Request, assignment_id: int):
    return await invoke(request, "submission_create", assignment_id)


@router.get("/teacher/submissions")
async def teacher_submissions(request: Request):
    return await invoke(request, "teacher_submissions")


@router.get("/teacher/submissions/{submission_id}")
async def submission_history(request: Request, submission_id: int):
    return await invoke(request, "submission_history", submission_id)


@router.get("/teacher/export.csv")
async def export_csv(request: Request):
    return await invoke(request, "teacher_export", "csv")


@router.get("/teacher/export.pdf")
async def export_pdf(request: Request):
    return await invoke(request, "teacher_export", "pdf")


@router.post("/submissions/{submission_id}/review")
async def review_submission(request: Request, submission_id: int):
    return await invoke(request, "review_submission", submission_id)
