from __future__ import annotations

import io
import json
import secrets
import time
from http import HTTPStatus
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from trainer.api import runtime
from trainer.api.errors import ApiError
from trainer.api.results import ActionResult, FileResult, RequestContext
from trainer.api.runtime import MATERIAL_ASSET_DIR, MAX_AUDIO_BODY, connect
from trainer.domain.materials import (
    validate_slug,
)
from trainer.infrastructure.storage import storage_from_env
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
        content=payload.content,
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
    raise error


def _material_index_payload(row: dict) -> dict:
    return {
        "id": row["slug"],
        "year": row["year"],
        "label": row["title"],
        "source": row["source"],
        "kind": row["kind"],
        "taskNumber": row["task_number"],
        "official": False,
        "status": row["status"],
    }


def _material_metadata(payload) -> dict:
    kind = payload.kind
    task_number = payload.taskNumber
    try:
        task_number = int(task_number) if task_number is not None else None
        year = int(payload.year)
    except (TypeError, ValueError) as error:
        raise ValueError("Проверьте год и номер задания") from error
    if kind == "full":
        task_number = None
    elif kind != "task" or task_number not in {1, 2, 3}:
        raise ValueError("Выберите тип материала и номер задания")
    content = payload.content
    if not isinstance(content, dict) or len(json.dumps(content, ensure_ascii=False)) > 150_000:
        raise ValueError("Содержание материала слишком велико")
    title = payload.title.strip()
    source = payload.source.strip()
    if not 2 <= len(title) <= 120 or not 2 <= len(source) <= 200 or not 2020 <= year <= 2100:
        raise ValueError("Проверьте название, год и источник материала")
    return {
        "slug": validate_slug(payload.slug),
        "kind": kind,
        "taskNumber": task_number,
        "title": title,
        "year": year,
        "source": source,
        "content": content,
    }


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
    mime_type = content_type.split(";", 1)[0].lower()
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ApiError("unsupported_image", "Поддерживаются JPG, PNG и WebP", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    length = len(body)
    if not 0 < length <= min(MAX_AUDIO_BODY, 5_000_000):
        raise ApiError("image_too_large", "Изображение превышает 5 МБ", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    with connect() as database:
        material = database.execute(
            "SELECT id FROM materials WHERE slug=? AND owner_id=?", (material_id, user["id"])
        ).fetchone()
    if not material:
        raise ApiError("material_not_found", "Материал не найден", HTTPStatus.NOT_FOUND)
    try:
        image = Image.open(io.BytesIO(body))
        image.load()
        if image.width < 320 or image.height < 240 or image.width * image.height > 20_000_000:
            raise ValueError
        image.thumbnail((1600, 1600))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        encoded = io.BytesIO()
        image.save(encoded, "WEBP", quality=84, method=6)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ApiError("invalid_image", "Некорректное изображение", HTTPStatus.UNPROCESSABLE_ENTITY) from error
    storage_key = f"materials/{material['id']}/{secrets.token_urlsafe(18)}.webp"
    temporary = Path(MATERIAL_ASSET_DIR / f".{secrets.token_hex(8)}.webp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_bytes(encoded.getvalue())
    storage = storage_from_env(MATERIAL_ASSET_DIR)
    try:
        storage.put(storage_key, temporary, "image/webp")
        with connect() as database:
            cursor = database.execute(
                "INSERT INTO material_assets(material_id,storage_key,mime_type,size_bytes,created_at) VALUES (?,?,?,?,?)",
                (material["id"], storage_key, "image/webp", len(encoded.getvalue()), int(time.time())),
            )
    except Exception:
        try:
            storage.delete(storage_key)
        except Exception:
            pass
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return ActionResult(
        {"asset": {"id": cursor.lastrowid, "url": f"/api/material-assets/{cursor.lastrowid}"}},
        status=HTTPStatus.CREATED,
    )


def material_asset_get(asset_id: int, user: dict | None) -> FileResult:
    with connect() as database:
        row = database.execute(
            """SELECT material_assets.*,materials.owner_id,materials.status FROM material_assets
               JOIN materials ON materials.id=material_assets.material_id WHERE material_assets.id=?""",
            (asset_id,),
        ).fetchone()
        allowed = bool(row) and bool(user) and (row["status"] == "published" or row["owner_id"] == user["id"])
    if not allowed:
        raise ApiError("asset_not_found", "Изображение не найдено", HTTPStatus.NOT_FOUND)
    return FileResult(key=row["storage_key"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])
