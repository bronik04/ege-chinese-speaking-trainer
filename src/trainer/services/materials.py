from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from trainer.domain.materials import editor_allowed, material_payload
from trainer.services.material_repository import (
    MaterialActor,
    MaterialAssetStorage,
    MaterialRecord,
    MaterialRepository,
)


def official_index(root: Path) -> list[dict]:
    return json.loads((root / "content/variants/index.json").read_text(encoding="utf-8"))


def official_detail(root: Path, material_id: str) -> dict | None:
    item = next((entry for entry in official_index(root) if entry["id"] == material_id), None)
    if not item:
        return None
    payload = json.loads((root / item["file"]).read_text(encoding="utf-8"))
    return {**payload, "kind": "full", "taskNumber": None, "official": True, "status": "published"}


def public_official_index(root: Path, authenticated: bool) -> list[dict]:
    entries = official_index(root)
    if not authenticated:
        entries = [entry for entry in entries if entry["id"] == "open-2026"]
    return [{**entry, "kind": "full", "taskNumber": None, "official": True, "status": "published"} for entry in entries]


def _material_index_payload(record: MaterialRecord) -> dict:
    return {
        "id": record.slug,
        "year": record.year,
        "label": record.title,
        "source": record.source,
        "kind": record.kind,
        "taskNumber": record.task_number,
        "official": False,
        "status": record.status,
    }


def _material_payload(record: MaterialRecord) -> dict:
    return material_payload(asdict(record))


class MaterialError(Exception):
    def __init__(self, reason: str, message: str | None = None):
        super().__init__(message or reason)
        self.reason = reason
        self.message = message


class MaterialService:
    def __init__(
        self,
        repository: MaterialRepository,
        *,
        project_root: Path,
        asset_root: Path,
        storage: MaterialAssetStorage,
        image_encoder: Callable[[bytes], bytes],
        editor_emails: str,
        max_image_body: int,
        now: Callable[[], int] = lambda: int(time.time()),
    ):
        self._repository = repository
        self._project_root = project_root
        self._asset_root = asset_root
        self._storage = storage
        self._image_encoder = image_encoder
        self._editor_emails = editor_emails
        self._max_image_body = max_image_body
        self._now = now

    def catalog(self, actor: MaterialActor | None) -> dict:
        items = public_official_index(self._project_root, actor is not None)
        if actor is not None:
            items.extend(_material_index_payload(record) for record in self._repository.published_materials())
        user = (
            {"id": actor.id, "email": actor.email, "emailVerified": actor.email_verified} if actor is not None else None
        )
        return {"materials": items, "canCreate": editor_allowed(user, self._editor_emails)}

    def mine(self, actor: MaterialActor) -> list[dict]:
        return [_material_index_payload(record) for record in self._repository.owned_materials(actor.id)]

    def detail(self, material_id: str, actor: MaterialActor | None) -> dict:
        official = official_detail(self._project_root, material_id)
        if official is not None:
            if actor is None and material_id != "open-2026":
                raise MaterialError("not_found")
            return official
        record = self._repository.material(material_id)
        if (
            record is None
            or actor is None
            or record.status == "archived"
            or (record.status != "published" and record.owner_id != actor.id)
        ):
            raise MaterialError("not_found")
        return _material_payload(record)
