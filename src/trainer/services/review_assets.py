from __future__ import annotations

import copy
import re
import secrets
import tempfile
import time
from contextlib import suppress
from pathlib import Path

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
    )


def copy_review_assets(
    database,
    request_id: int,
    material_snapshot: dict,
    source_storage,
    target_storage,
    external_created_keys: list[str] | None = None,
) -> dict:
    rewritten = copy.deepcopy(material_snapshot)
    urls: dict[int, str] = {}
    created_keys: list[str] = []
    created_ids: list[int] = []

    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        if not isinstance(value, str):
            return value
        match = MATERIAL_ASSET_URL.fullmatch(value)
        if not match:
            return value
        source_id = int(match.group(1))
        if source_id in urls:
            return urls[source_id]
        row = database.execute(
            "SELECT storage_key,mime_type,size_bytes FROM material_assets WHERE id=?", (source_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Material asset {source_id} does not exist")
        suffix = Path(row["storage_key"]).suffix or ".bin"
        target_key = f"review-requests/{request_id}/{secrets.token_urlsafe(18)}{suffix}"
        created_keys.append(target_key)
        if external_created_keys is not None:
            external_created_keys.append(target_key)
        data = source_storage.read(row["storage_key"])
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                temporary.write(data)
                temporary_path = Path(temporary.name)
            target_storage.put(target_key, temporary_path, row["mime_type"])
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
        cursor = database.execute(
            """INSERT INTO review_request_assets(request_id,storage_key,mime_type,size_bytes,created_at)
               VALUES (?,?,?,?,?)""",
            (request_id, target_key, row["mime_type"], len(data), int(time.time())),
        )
        created_ids.append(cursor.lastrowid)
        snapshot_url = f"/api/review-assets/{cursor.lastrowid}"
        urls[source_id] = snapshot_url
        return snapshot_url

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
