from __future__ import annotations

import io
import json
import os
import secrets
import time
from http import HTTPStatus
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from trainer.api.errors import ApiError
from trainer.api.results import ActionResult, FileResult, RequestContext
from trainer.api.runtime import MATERIAL_ASSET_DIR, MAX_AUDIO_BODY, ROOT, connect
from trainer.domain.materials import (
    build_content,
    editor_allowed,
    material_asset_ids,
    material_payload,
    validate_slug,
)
from trainer.infrastructure.database.core import INTEGRITY_ERRORS
from trainer.infrastructure.storage import storage_from_env
from trainer.services import accounts as account_services
from trainer.services.materials import official_detail, public_official_index


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


def _assignment_references_material_asset(database, user_id: int, asset_id: int) -> bool:
    """Участвует ли пользователь в назначении, чей снимок ссылается на этот ассет.

    Назначения, выданные до перехода на копии в assignment_material_assets,
    хранят в снимке прямые ссылки /api/material-assets/N. Архивирование
    материала не должно ломать уже выданные работы, но и открывать его
    изображения всем подряд нельзя.
    """
    return bool(
        database.execute(
            """SELECT 1 FROM assignments
               LEFT JOIN group_members ON group_members.group_id = assignments.group_id
                    AND group_members.user_id = ?
               WHERE assignments.material_snapshot_json LIKE ?
                 AND (assignments.teacher_id = ? OR group_members.user_id IS NOT NULL)
               LIMIT 1""",
            (user_id, f'%"/api/material-assets/{asset_id}"%', user_id),
        ).fetchone()
    )


def materials_list(user: dict | None) -> ActionResult:
    items = public_official_index(ROOT, bool(user))
    if user:
        with connect() as database:
            rows = database.execute(
                "SELECT * FROM materials WHERE status = 'published' ORDER BY year DESC, updated_at DESC"
            ).fetchall()
        items.extend(_material_index_payload(dict(row)) for row in rows)
    return ActionResult(
        {
            "materials": items,
            "canCreate": editor_allowed(user, os.environ.get("TRAINER_EDITOR_EMAILS", "")),
        }
    )


def materials_mine(user: dict) -> ActionResult:
    with connect() as database:
        rows = database.execute(
            "SELECT * FROM materials WHERE owner_id = ? AND status != 'archived' ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
    return ActionResult({"materials": [_material_index_payload(dict(row)) for row in rows]})


def material_get(material_id: str, user: dict | None) -> ActionResult:
    official = official_detail(ROOT, material_id)
    if official:
        if not user and material_id != "open-2026":
            raise ApiError("material_not_found", "Материал не найден", HTTPStatus.NOT_FOUND)
        return ActionResult({"material": official})
    with connect() as database:
        row = database.execute("SELECT * FROM materials WHERE slug = ?", (material_id,)).fetchone()
    if (
        not row
        or not user
        or row["status"] == "archived"
        or (row["status"] != "published" and row["owner_id"] != user["id"])
    ):
        raise ApiError("material_not_found", "Материал не найден", HTTPStatus.NOT_FOUND)
    return ActionResult({"material": material_payload(dict(row))})


def material_create(payload, user: dict, context: RequestContext) -> ActionResult:
    try:
        normalized = _material_metadata(payload)
    except ValueError as error:
        raise ApiError("invalid_material", str(error), HTTPStatus.BAD_REQUEST) from error
    now = int(time.time())
    try:
        with connect() as database:
            cursor = database.execute(
                """INSERT INTO materials(slug,owner_id,kind,task_number,title,year,source,status,content_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,'draft',?,?,?)""",
                (
                    normalized["slug"],
                    user["id"],
                    normalized["kind"],
                    normalized["taskNumber"],
                    normalized["title"],
                    normalized["year"],
                    normalized["source"],
                    json.dumps(normalized["content"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            account_services.audit(
                database,
                "material_created",
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                user_id=user["id"],
                email=user["email"],
                details={"materialId": cursor.lastrowid},
            )
    except INTEGRITY_ERRORS as error:
        raise ApiError(
            "material_slug_exists", "Материал с таким идентификатором уже существует", HTTPStatus.CONFLICT
        ) from error
    return ActionResult({"material": {"id": normalized["slug"], "status": "draft"}}, status=HTTPStatus.CREATED)


def material_update(material_id: str, payload, user: dict, context: RequestContext) -> ActionResult:
    try:
        normalized = _material_metadata(payload)
    except ValueError as error:
        raise ApiError("invalid_material", str(error), HTTPStatus.BAD_REQUEST) from error
    try:
        with connect() as database:
            cursor = database.execute(
                """UPDATE materials SET slug=?,kind=?,task_number=?,title=?,year=?,source=?,content_json=?,
                       status='draft',published_at=NULL,updated_at=? WHERE slug=? AND owner_id=?""",
                (
                    normalized["slug"],
                    normalized["kind"],
                    normalized["taskNumber"],
                    normalized["title"],
                    normalized["year"],
                    normalized["source"],
                    json.dumps(normalized["content"], ensure_ascii=False),
                    int(time.time()),
                    material_id,
                    user["id"],
                ),
            )
            if not cursor.rowcount:
                raise ApiError("material_not_found", "Материал не найден", HTTPStatus.NOT_FOUND)
    except ApiError:
        raise
    except INTEGRITY_ERRORS as error:
        raise ApiError(
            "material_slug_exists", "Материал с таким идентификатором уже существует", HTTPStatus.CONFLICT
        ) from error
    return ActionResult({"material": {"id": normalized["slug"], "status": "draft"}})


def material_publish(material_id: str, user: dict, context: RequestContext) -> ActionResult:
    unused_assets = []
    with connect() as database:
        row = database.execute(
            "SELECT * FROM materials WHERE slug = ? AND owner_id = ?", (material_id, user["id"])
        ).fetchone()
        if not row:
            raise ApiError("material_not_found", "Материал не найден", HTTPStatus.NOT_FOUND)
        try:
            content = build_content(row["kind"], row["task_number"], json.loads(row["content_json"]))
            asset_ids = material_asset_ids(content)
        except ValueError as error:
            raise ApiError("material_incomplete", str(error), HTTPStatus.BAD_REQUEST) from error
        if asset_ids:
            placeholders = ",".join("?" for _ in asset_ids)
            owned = database.execute(
                f"SELECT id FROM material_assets WHERE material_id=? AND id IN ({placeholders})",
                (row["id"], *sorted(asset_ids)),
            ).fetchall()
            if len(owned) != len(asset_ids):
                raise ApiError(
                    "invalid_material_asset", "Одно из изображений не принадлежит материалу", HTTPStatus.BAD_REQUEST
                )
        now = int(time.time())
        database.execute(
            "UPDATE materials SET content_json=?,status='published',published_at=?,updated_at=? WHERE id=?",
            (json.dumps(content, ensure_ascii=False), now, now, row["id"]),
        )
        all_assets = database.execute(
            "SELECT id, storage_key FROM material_assets WHERE material_id = ?", (row["id"],)
        ).fetchall()
        assignment_asset_ids = set()
        snapshots = database.execute(
            "SELECT material_snapshot_json FROM assignments WHERE material_snapshot_json IS NOT NULL"
        ).fetchall()
        for snapshot in snapshots:
            try:
                snapshot_payload = json.loads(snapshot["material_snapshot_json"])
                assignment_asset_ids.update(material_asset_ids(snapshot_payload.get("tasks", {})))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        retained_asset_ids = asset_ids | assignment_asset_ids
        unused_assets = [asset for asset in all_assets if asset["id"] not in retained_asset_ids]
        for asset in unused_assets:
            database.execute("DELETE FROM material_assets WHERE id = ?", (asset["id"],))
        account_services.audit(
            database,
            "material_published",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            user_id=user["id"],
            email=user["email"],
            details={"materialId": row["id"]},
        )
    storage = storage_from_env(MATERIAL_ASSET_DIR)
    for asset in unused_assets:
        try:
            storage.delete(asset["storage_key"])
        except Exception:
            continue
    return ActionResult({"material": {"id": material_id, "status": "published"}})


def material_delete(material_id: str, user: dict, context: RequestContext) -> ActionResult:
    with connect() as database:
        row = database.execute(
            "SELECT id FROM materials WHERE slug=? AND owner_id=?", (material_id, user["id"])
        ).fetchone()
        if not row:
            raise ApiError("material_not_found", "Материал не найден", HTTPStatus.NOT_FOUND)
        database.execute(
            "UPDATE materials SET status='archived', published_at=NULL, updated_at=? WHERE id=?",
            (int(time.time()), row["id"]),
        )
    return ActionResult({"ok": True})


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
        if row and user and not allowed and row["status"] == "archived":
            allowed = _assignment_references_material_asset(database, user["id"], asset_id)
    if not allowed:
        raise ApiError("asset_not_found", "Изображение не найдено", HTTPStatus.NOT_FOUND)
    return FileResult(key=row["storage_key"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])
