from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from trainer.api import runtime
from trainer.api.controllers import recordings as actions
from trainer.api.dependencies import require_authenticated
from trainer.api.routes import file_response

router = APIRouter(prefix="/api")


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


@router.get("/review-recordings/{recording_id}")
async def get_review_recording(
    recording_id: int,
    request: Request,
    user: dict = Depends(require_authenticated),
):
    stored = await run_in_threadpool(actions.review_recording_get, recording_id, user)
    range_headers = request.headers.getlist("Range")
    return file_response(
        stored,
        range_headers[0] if range_headers else None,
        range_header_count=len(range_headers),
    )


@router.get("/review-assets/{asset_id}")
async def get_review_asset(
    asset_id: int,
    request: Request,
    user: dict = Depends(require_authenticated),
):
    stored = await run_in_threadpool(actions.review_asset_get, asset_id, user)
    range_headers = request.headers.getlist("Range")
    return file_response(
        stored,
        range_headers[0] if range_headers else None,
        range_header_count=len(range_headers),
        storage_root=runtime.ASSIGNMENT_ASSET_DIR,
    )
