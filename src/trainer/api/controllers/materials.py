from __future__ import annotations

from http import HTTPStatus

from trainer.api import runtime
from trainer.api.errors import ApiError
from trainer.api.results import ActionResult, FileResult, RequestContext
from trainer.services.material_repository import (
    MaterialActor,
    MaterialRequestData,
    MaterialRequestMetadata,
)
from trainer.services.materials import MaterialError


def _actor(user: dict | None) -> MaterialActor | None:
    return MaterialActor(user["id"], user["email"], bool(user.get("emailVerified"))) if user is not None else None


def _required_actor(user: dict) -> MaterialActor:
    actor = _actor(user)
    assert actor is not None
    return actor


def _request_data(payload) -> MaterialRequestData:
    return MaterialRequestData(
        slug=payload.slug,
        kind=payload.kind,
        task_number=payload.taskNumber,
        title=payload.title,
        year=payload.year,
        source=payload.source,
        content=payload.content.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def _metadata(context: RequestContext) -> MaterialRequestMetadata:
    return MaterialRequestMetadata(context.client_ip, context.user_agent)


def _service_error(error: MaterialError) -> ApiError:
    if error.reason == "not_found":
        return ApiError("material_not_found", "Материал не найден", HTTPStatus.NOT_FOUND)
    if error.reason == "invalid_metadata":
        return ApiError("invalid_material", error.message or "Некорректный материал", HTTPStatus.BAD_REQUEST)
    if error.reason == "slug_exists":
        return ApiError(
            "material_slug_exists",
            "Материал с таким идентификатором уже существует",
            HTTPStatus.CONFLICT,
        )
    if error.reason == "incomplete":
        return ApiError(
            "material_incomplete",
            error.message or "Материал не заполнен",
            HTTPStatus.BAD_REQUEST,
        )
    if error.reason == "foreign_asset":
        return ApiError(
            "invalid_material_asset",
            "Одно из изображений не принадлежит материалу",
            HTTPStatus.BAD_REQUEST,
        )
    if error.reason == "unsupported_image":
        return ApiError(
            "unsupported_image",
            "Поддерживаются JPG, PNG и WebP",
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        )
    if error.reason == "image_too_large":
        return ApiError(
            "image_too_large",
            "Изображение превышает 5 МБ",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    if error.reason == "invalid_image":
        return ApiError(
            "invalid_image",
            "Некорректное изображение",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if error.reason == "asset_not_found":
        return ApiError(
            "asset_not_found",
            "Изображение не найдено",
            HTTPStatus.NOT_FOUND,
        )
    raise error


def materials_list(user: dict | None) -> ActionResult:
    return ActionResult(runtime.material_service().catalog(_actor(user)))


def materials_mine(user: dict) -> ActionResult:
    return ActionResult({"materials": runtime.material_service().mine(_required_actor(user))})


def material_get(material_id: str, user: dict | None) -> ActionResult:
    try:
        material = runtime.material_service().detail(material_id, _actor(user))
    except MaterialError as error:
        raise _service_error(error) from error
    return ActionResult({"material": material})


def material_create(payload, user: dict, context: RequestContext) -> ActionResult:
    try:
        material = runtime.material_service().create(
            _request_data(payload),
            _required_actor(user),
            _metadata(context),
        )
    except MaterialError as error:
        raise _service_error(error) from error
    return ActionResult({"material": material}, status=HTTPStatus.CREATED)


def material_update(material_id: str, payload, user: dict, context: RequestContext) -> ActionResult:
    try:
        material = runtime.material_service().update(
            material_id,
            _request_data(payload),
            _required_actor(user),
            _metadata(context),
        )
    except MaterialError as error:
        raise _service_error(error) from error
    return ActionResult({"material": material})


def material_publish(material_id: str, user: dict, context: RequestContext) -> ActionResult:
    try:
        material = runtime.material_service().publish(
            material_id,
            _required_actor(user),
            _metadata(context),
        )
    except MaterialError as error:
        raise _service_error(error) from error
    return ActionResult({"material": material})


def material_delete(material_id: str, user: dict, context: RequestContext) -> ActionResult:
    try:
        result = runtime.material_service().archive(material_id, _required_actor(user))
    except MaterialError as error:
        raise _service_error(error) from error
    return ActionResult(result)


def material_asset_create(
    material_id: str, body: bytes, content_type: str, user: dict, context: RequestContext
) -> ActionResult:
    try:
        asset = runtime.material_service().upload_asset(
            material_id,
            body,
            content_type,
            _required_actor(user),
        )
    except MaterialError as error:
        raise _service_error(error) from error
    return ActionResult(
        {"asset": asset},
        status=HTTPStatus.CREATED,
    )


def material_asset_get(asset_id: int, user: dict | None) -> FileResult:
    try:
        asset = runtime.material_service().asset(asset_id, _actor(user))
    except MaterialError as error:
        raise _service_error(error) from error
    return FileResult(
        key=asset.storage_key,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
    )
