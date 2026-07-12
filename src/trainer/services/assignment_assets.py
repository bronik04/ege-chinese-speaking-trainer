from __future__ import annotations

import copy
import re
import secrets
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from trainer.infrastructure.storage import AudioStorage, storage_from_env

ASSET_URL = re.compile(r"/api/(material|assignment)-assets/(\d+)")


def copy_assignment_assets_from_env(
    database,
    assignment_id: int,
    material: dict,
    source_root: Path,
    target_root: Path,
    created_keys: list[str] | None = None,
) -> dict:
    arguments = (database, assignment_id, material, storage_from_env(source_root), storage_from_env(target_root))
    return (
        copy_assignment_assets(*arguments, created_keys)
        if created_keys is not None
        else copy_assignment_assets(*arguments)
    )


def read_assignment_asset(root: Path, key: str) -> bytes:
    return storage_from_env(root).read(key)


def delete_assignment_assets(root: Path, keys: list[str]) -> None:
    storage = storage_from_env(root)
    for key in keys:
        with suppress(Exception):
            storage.delete(key)


def copy_assignment_assets(
    database,
    assignment_id: int,
    material: dict,
    source_storage: AudioStorage,
    target_storage: AudioStorage,
    external_created_keys: list[str] | None = None,
) -> dict:
    rewritten = copy.deepcopy(material)
    urls: dict[tuple[str, int], str] = {}
    created_keys: list[str] = []
    created_ids: list[int] = []

    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        if not isinstance(value, str):
            return value
        match = ASSET_URL.fullmatch(value)
        if not match:
            return value
        source_kind = match.group(1)
        source_id = int(match.group(2))
        cache_key = (source_kind, source_id)
        if cache_key in urls:
            return urls[cache_key]
        source_table = "material_assets" if source_kind == "material" else "assignment_material_assets"
        row = database.execute(
            f"SELECT storage_key,mime_type,size_bytes FROM {source_table} WHERE id=?",
            (source_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"{source_kind.title()} asset {source_id} does not exist")
        suffix = Path(row["storage_key"]).suffix or ".bin"
        target_key = f"assignments/{assignment_id}/{secrets.token_urlsafe(18)}{suffix}"
        created_keys.append(target_key)
        if external_created_keys is not None:
            external_created_keys.append(target_key)
        active_source_storage = source_storage if source_kind == "material" else target_storage
        data = active_source_storage.read(row["storage_key"])
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
            """INSERT INTO assignment_material_assets
               (assignment_id,storage_key,mime_type,size_bytes,created_at) VALUES (?,?,?,?,?)""",
            (assignment_id, target_key, row["mime_type"], len(data), int(time.time())),
        )
        created_ids.append(cursor.lastrowid)
        snapshot_url = f"/api/assignment-assets/{cursor.lastrowid}"
        urls[cache_key] = snapshot_url
        return snapshot_url

    try:
        return replace(rewritten)
    except Exception:
        for asset_id in created_ids:
            with suppress(Exception):
                database.execute("DELETE FROM assignment_material_assets WHERE id=?", (asset_id,))
        for key in created_keys:
            with suppress(Exception):
                target_storage.delete(key)
        raise
