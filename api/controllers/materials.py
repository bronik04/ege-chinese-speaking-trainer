from __future__ import annotations

import io
import json
import secrets
import time
from http import HTTPStatus
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from api.runtime import MATERIAL_ASSET_DIR, MAX_AUDIO_BODY, ROOT, connect
from backend.database import INTEGRITY_ERRORS
from backend.materials import (
    build_content,
    editor_allowed,
    material_asset_ids,
    material_payload,
    official_detail,
    public_official_index,
    validate_slug,
)
from backend.storage import storage_from_env


class MaterialControllerMixin:
    def materials_list(self) -> None:
        user = self.current_user()
        items = public_official_index(ROOT, bool(user))
        if user:
            with connect() as database:
                rows = database.execute(
                    "SELECT * FROM materials WHERE status = 'published' ORDER BY year DESC, updated_at DESC"
                ).fetchall()
            items.extend(self.material_index_payload(dict(row)) for row in rows)
        self.send_json({"materials": items, "canCreate": editor_allowed(user)})

    def materials_mine(self) -> None:
        user = self.require_material_editor()
        if not user:
            return
        with connect() as database:
            rows = database.execute(
                "SELECT * FROM materials WHERE owner_id = ? ORDER BY updated_at DESC", (user["id"],)
            ).fetchall()
        self.send_json({"materials": [self.material_index_payload(dict(row)) for row in rows]})

    def material_get(self, material_id: str) -> None:
        user = self.current_user()
        official = official_detail(ROOT, material_id)
        if official:
            if not user and material_id != "open-2026":
                self.send_error_json(HTTPStatus.NOT_FOUND, "Материал не найден", "material_not_found")
                return
            self.send_json({"material": official})
            return
        with connect() as database:
            row = database.execute("SELECT * FROM materials WHERE slug = ?", (material_id,)).fetchone()
        if not row or not user or (row["status"] != "published" and row["owner_id"] != user["id"]):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Материал не найден", "material_not_found")
            return
        self.send_json({"material": material_payload(dict(row))})

    def material_create(self) -> None:
        user = self.require_material_editor()
        if not user:
            return
        payload = self.read_json()
        if payload is None:
            return
        try:
            normalized = self.material_metadata(payload)
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error), "invalid_material")
            return
        now = int(time.time())
        try:
            with connect() as database:
                cursor = database.execute(
                    """INSERT INTO materials(slug,owner_id,kind,task_number,title,year,source,status,content_json,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,'draft',?,?,?)""",
                    (
                        normalized["slug"], user["id"], normalized["kind"], normalized["taskNumber"],
                        normalized["title"], normalized["year"], normalized["source"],
                        json.dumps(normalized["content"], ensure_ascii=False), now, now,
                    ),
                )
                self.audit(database, "material_created", user_id=user["id"], email=user["email"], details={"materialId": cursor.lastrowid})
        except INTEGRITY_ERRORS:
            self.send_error_json(HTTPStatus.CONFLICT, "Материал с таким идентификатором уже существует", "material_slug_exists")
            return
        self.send_json({"material": {"id": normalized["slug"], "status": "draft"}}, HTTPStatus.CREATED)

    def material_update(self, material_id: str) -> None:
        user = self.require_material_editor()
        if not user:
            return
        payload = self.read_json()
        if payload is None:
            return
        try:
            normalized = self.material_metadata(payload)
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error), "invalid_material")
            return
        try:
            with connect() as database:
                cursor = database.execute(
                    """UPDATE materials SET slug=?,kind=?,task_number=?,title=?,year=?,source=?,content_json=?,
                           status='draft',published_at=NULL,updated_at=? WHERE slug=? AND owner_id=?""",
                    (
                        normalized["slug"], normalized["kind"], normalized["taskNumber"], normalized["title"],
                        normalized["year"], normalized["source"], json.dumps(normalized["content"], ensure_ascii=False),
                        int(time.time()), material_id, user["id"],
                    ),
                )
                if not cursor.rowcount:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "Материал не найден", "material_not_found")
                    return
        except INTEGRITY_ERRORS:
            self.send_error_json(HTTPStatus.CONFLICT, "Материал с таким идентификатором уже существует", "material_slug_exists")
            return
        self.send_json({"material": {"id": normalized["slug"], "status": "draft"}})

    def material_publish(self, material_id: str) -> None:
        user = self.require_material_editor()
        if not user:
            return
        with connect() as database:
            row = database.execute(
                "SELECT * FROM materials WHERE slug = ? AND owner_id = ?", (material_id, user["id"])
            ).fetchone()
            if not row:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Материал не найден", "material_not_found")
                return
            try:
                content = build_content(row["kind"], row["task_number"], json.loads(row["content_json"]))
                asset_ids = material_asset_ids(content)
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error), "material_incomplete")
                return
            if asset_ids:
                placeholders = ",".join("?" for _ in asset_ids)
                owned = database.execute(
                    f"SELECT id FROM material_assets WHERE material_id=? AND id IN ({placeholders})",
                    (row["id"], *sorted(asset_ids)),
                ).fetchall()
                if len(owned) != len(asset_ids):
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "Одно из изображений не принадлежит материалу", "invalid_material_asset")
                    return
            now = int(time.time())
            database.execute(
                "UPDATE materials SET content_json=?,status='published',published_at=?,updated_at=? WHERE id=?",
                (json.dumps(content, ensure_ascii=False), now, now, row["id"]),
            )
            self.audit(database, "material_published", user_id=user["id"], email=user["email"], details={"materialId": row["id"]})
        self.send_json({"material": {"id": material_id, "status": "published"}})

    def material_delete(self, material_id: str) -> None:
        user = self.require_material_editor()
        if not user:
            return
        with connect() as database:
            row = database.execute("SELECT id FROM materials WHERE slug=? AND owner_id=?", (material_id, user["id"])).fetchone()
            if not row:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Материал не найден", "material_not_found")
                return
            assets = database.execute("SELECT storage_key FROM material_assets WHERE material_id=?", (row["id"],)).fetchall()
            database.execute("DELETE FROM materials WHERE id=?", (row["id"],))
        storage = storage_from_env(MATERIAL_ASSET_DIR)
        for asset in assets:
            try:
                storage.delete(asset["storage_key"])
            except Exception:
                continue
        self.send_json({"ok": True})

    def material_asset_create(self, material_id: str) -> None:
        user = self.require_material_editor()
        if not user:
            return
        mime_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            self.send_error_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Поддерживаются JPG, PNG и WebP", "unsupported_image")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= min(MAX_AUDIO_BODY, 5_000_000):
            self.send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Изображение превышает 5 МБ", "image_too_large")
            return
        with connect() as database:
            material = database.execute("SELECT id FROM materials WHERE slug=? AND owner_id=?", (material_id, user["id"])).fetchone()
        if not material:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Материал не найден", "material_not_found")
            return
        try:
            image = Image.open(io.BytesIO(self.rfile.read(length)))
            image.load()
            if image.width < 320 or image.height < 240 or image.width * image.height > 20_000_000:
                raise ValueError
            image.thumbnail((1600, 1600))
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGB")
            encoded = io.BytesIO()
            image.save(encoded, "WEBP", quality=84, method=6)
        except (UnidentifiedImageError, OSError, ValueError):
            self.send_error_json(HTTPStatus.UNPROCESSABLE_ENTITY, "Некорректное изображение", "invalid_image")
            return
        storage_key = f"materials/{material['id']}/{secrets.token_urlsafe(18)}.webp"
        temporary = Path(MATERIAL_ASSET_DIR / f".{secrets.token_hex(8)}.webp")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(encoded.getvalue())
        try:
            storage_from_env(MATERIAL_ASSET_DIR).put(storage_key, temporary, "image/webp")
            with connect() as database:
                cursor = database.execute(
                    "INSERT INTO material_assets(material_id,storage_key,mime_type,size_bytes,created_at) VALUES (?,?,?,?,?)",
                    (material["id"], storage_key, "image/webp", len(encoded.getvalue()), int(time.time())),
                )
        finally:
            temporary.unlink(missing_ok=True)
        self.send_json({"asset": {"id": cursor.lastrowid, "url": f"/api/material-assets/{cursor.lastrowid}"}}, HTTPStatus.CREATED)

    def material_asset_get(self, asset_id: int) -> None:
        user = self.current_user()
        with connect() as database:
            row = database.execute(
                """SELECT material_assets.*,materials.owner_id,materials.status FROM material_assets
                   JOIN materials ON materials.id=material_assets.material_id WHERE material_assets.id=?""",
                (asset_id,),
            ).fetchone()
        if not row or not user or (row["status"] != "published" and row["owner_id"] != user["id"]):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Изображение не найдено", "asset_not_found")
            return
        try:
            data = storage_from_env(MATERIAL_ASSET_DIR).read(row["storage_key"])
        except (FileNotFoundError, OSError, ValueError):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Изображение не найдено", "asset_not_found")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", row["mime_type"])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def require_material_editor(self) -> dict | None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Войдите, чтобы создавать материалы", "authentication_required")
            return None
        if not editor_allowed(user):
            self.send_error_json(HTTPStatus.FORBIDDEN, "Создание материалов недоступно", "editor_forbidden")
            return None
        return user

    @staticmethod
    def material_metadata(payload: dict) -> dict:
        kind = str(payload.get("kind", ""))
        task_number = payload.get("taskNumber")
        try:
            task_number = int(task_number) if task_number is not None else None
            year = int(payload.get("year"))
        except (TypeError, ValueError) as error:
            raise ValueError("Проверьте год и номер задания") from error
        if kind == "full":
            task_number = None
        elif kind != "task" or task_number not in {1, 2, 3}:
            raise ValueError("Выберите тип материала и номер задания")
        content = payload.get("content")
        if not isinstance(content, dict) or len(json.dumps(content, ensure_ascii=False)) > 150_000:
            raise ValueError("Содержание материала слишком велико")
        title = str(payload.get("title", "")).strip()
        source = str(payload.get("source", "")).strip()
        if not 2 <= len(title) <= 120 or not 2 <= len(source) <= 200 or not 2020 <= year <= 2100:
            raise ValueError("Проверьте название, год и источник материала")
        return {
            "slug": validate_slug(str(payload.get("slug", ""))),
            "kind": kind,
            "taskNumber": task_number,
            "title": title,
            "year": year,
            "source": source,
            "content": content,
        }

    @staticmethod
    def material_index_payload(row: dict) -> dict:
        return {
            "id": row["slug"], "year": row["year"], "label": row["title"], "source": row["source"],
            "kind": row["kind"], "taskNumber": row["task_number"], "official": False, "status": row["status"],
        }
