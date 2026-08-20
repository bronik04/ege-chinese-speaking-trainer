from __future__ import annotations

import copy
import mimetypes
import re
import secrets
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import unquote

from trainer.infrastructure.storage import storage_from_env

MATERIAL_ASSET_URL = re.compile(r"/api/material-assets/(\d+)")


def copy_review_assets_from_env(database, request_id: int, material_snapshot: dict, created_keys: list[str]) -> dict:
    from trainer.api import runtime

    return copy_review_assets(
        database,
        request_id,
        material_snapshot,
        storage_from_env(runtime.MATERIAL_ASSET_DIR),
        storage_from_env(runtime.ASSIGNMENT_ASSET_DIR),
        created_keys,
        public_root=runtime.ROOT / "public",
    )


def copy_review_assets(
    database,
    request_id: int,
    material_snapshot: dict,
    source_storage,
    target_storage,
    external_created_keys: list[str] | None = None,
    *,
    public_root: Path | None = None,
) -> dict:
    rewritten = copy.deepcopy(material_snapshot)
    urls: dict[tuple[str, object], str] = {}
    created_keys: list[str] = []
    created_ids: list[int] = []

    def store_copy(cache_key: tuple[str, object], data: bytes, suffix: str, mime_type: str) -> str:
        if cache_key in urls:
            return urls[cache_key]
        target_key = f"review-requests/{request_id}/{secrets.token_urlsafe(18)}{suffix}"
        created_keys.append(target_key)
        if external_created_keys is not None:
            external_created_keys.append(target_key)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                temporary.write(data)
                temporary_path = Path(temporary.name)
            target_storage.put(target_key, temporary_path, mime_type)
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
        cursor = database.execute(
            """INSERT INTO review_request_assets(request_id,storage_key,mime_type,size_bytes,created_at)
               VALUES (?,?,?,?,?)""",
            (request_id, target_key, mime_type, len(data), int(time.time())),
        )
        created_ids.append(cursor.lastrowid)
        snapshot_url = f"/api/review-assets/{cursor.lastrowid}"
        urls[cache_key] = snapshot_url
        return snapshot_url

    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        if not isinstance(value, str):
            return value
        match = MATERIAL_ASSET_URL.fullmatch(value)
        if match:
            source_id = int(match.group(1))
            cache_key = ("material", source_id)
            if cache_key in urls:
                return urls[cache_key]
            row = database.execute(
                "SELECT storage_key,mime_type,size_bytes FROM material_assets WHERE id=?", (source_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Material asset {source_id} does not exist")
            suffix = Path(row["storage_key"]).suffix or ".bin"
            return store_copy(cache_key, source_storage.read(row["storage_key"]), suffix, row["mime_type"])

        relative_url = unquote(value).removeprefix("/")
        if not relative_url.startswith("assets/variants/"):
            return value
        if public_root is None:
            raise ValueError("Official review asset requires a public root")
        approved_root = public_root.resolve()
        source_path = (approved_root / relative_url).resolve()
        if approved_root not in source_path.parents or not source_path.is_file():
            raise ValueError("Official review asset is outside the public root or missing")
        mime_type = mimetypes.guess_type(source_path.name)[0]
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("Official review asset is not a supported image")
        return store_copy(("public", source_path), source_path.read_bytes(), source_path.suffix, mime_type)

    try:
        return replace(rewritten)
    except Exception:
        for asset_id in created_ids:
            with suppress(Exception):
                database.execute("DELETE FROM review_request_assets WHERE id=?", (asset_id,))
        for key in created_keys:
            with suppress(Exception):
                target_storage.delete(key)
        raise
