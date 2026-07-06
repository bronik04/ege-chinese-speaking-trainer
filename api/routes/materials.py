from fastapi import APIRouter, Request

from api.http import invoke
from api.schemas import MaterialRequest

router = APIRouter(prefix="/api")


@router.get("/materials")
async def list_materials(request: Request):
    return await invoke(request, "materials_list")


@router.get("/materials/mine")
async def my_materials(request: Request):
    return await invoke(request, "materials_mine")


@router.get("/materials/{material_id}")
async def get_material(request: Request, material_id: str):
    return await invoke(request, "material_get", material_id)


@router.post("/materials")
async def create_material(request: Request, payload: MaterialRequest):
    return await invoke(request, "material_create", payload=payload)


@router.put("/materials/{material_id}")
async def update_material(request: Request, material_id: str, payload: MaterialRequest):
    return await invoke(request, "material_update", material_id, payload=payload)


@router.post("/materials/{material_id}/publish")
async def publish_material(request: Request, material_id: str):
    return await invoke(request, "material_publish", material_id)


@router.delete("/materials/{material_id}")
async def delete_material(request: Request, material_id: str):
    return await invoke(request, "material_delete", material_id)


@router.post("/materials/{material_id}/assets")
async def create_material_asset(request: Request, material_id: str):
    return await invoke(request, "material_asset_create", material_id)


@router.get("/material-assets/{asset_id}")
async def get_material_asset(request: Request, asset_id: int):
    return await invoke(request, "material_asset_get", asset_id)
