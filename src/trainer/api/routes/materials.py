from http import HTTPStatus

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from trainer.api import runtime
from trainer.api.controllers import materials as actions
from trainer.api.dependencies import current_user_or_none, request_context, require_material_editor
from trainer.api.errors import ApiError
from trainer.api.routes import respond
from trainer.api.schemas import MaterialRequest
from trainer.infrastructure.storage import storage_from_env

router = APIRouter(prefix="/api")


@router.get("/materials")
async def list_materials(user: dict | None = Depends(current_user_or_none)):
    result = await run_in_threadpool(actions.materials_list, user)
    return respond(result)


@router.get("/materials/mine")
async def my_materials(user: dict = Depends(require_material_editor)):
    result = await run_in_threadpool(actions.materials_mine, user)
    return respond(result)


@router.get("/materials/{material_id}")
async def get_material(material_id: str, user: dict | None = Depends(current_user_or_none)):
    result = await run_in_threadpool(actions.material_get, material_id, user)
    return respond(result)


@router.post("/materials")
async def create_material(request: Request, payload: MaterialRequest, user: dict = Depends(require_material_editor)):
    result = await run_in_threadpool(actions.material_create, payload, user, request_context(request))
    return respond(result)


@router.put("/materials/{material_id}")
async def update_material(
    request: Request, material_id: str, payload: MaterialRequest, user: dict = Depends(require_material_editor)
):
    result = await run_in_threadpool(actions.material_update, material_id, payload, user, request_context(request))
    return respond(result)


@router.post("/materials/{material_id}/publish")
async def publish_material(request: Request, material_id: str, user: dict = Depends(require_material_editor)):
    result = await run_in_threadpool(actions.material_publish, material_id, user, request_context(request))
    return respond(result)


@router.delete("/materials/{material_id}")
async def delete_material(request: Request, material_id: str, user: dict = Depends(require_material_editor)):
    result = await run_in_threadpool(actions.material_delete, material_id, user, request_context(request))
    return respond(result)


@router.post("/materials/{material_id}/assets")
async def create_material_asset(material_id: str, request: Request, user: dict = Depends(require_material_editor)):
    body = await request.body()
    result = await run_in_threadpool(
        actions.material_asset_create,
        material_id,
        body,
        request.headers.get("Content-Type", ""),
        user,
        request_context(request),
    )
    return respond(result)


@router.get("/material-assets/{asset_id}")
async def get_material_asset(asset_id: int, user: dict | None = Depends(current_user_or_none)):
    # Временная реализация до задачи 14: читает файл целиком в маршруте.
    # file_response() из задачи 14 заменит это на FileResponse с поддержкой Range.
    stored = await run_in_threadpool(actions.material_asset_get, asset_id, user)
    try:
        data = await run_in_threadpool(storage_from_env(runtime.MATERIAL_ASSET_DIR).read, stored.key)
    except (FileNotFoundError, OSError, ValueError):
        raise ApiError("asset_not_found", "Изображение не найдено", HTTPStatus.NOT_FOUND) from None
    return Response(
        content=data,
        media_type=stored.mime_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
