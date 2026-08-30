from __future__ import annotations

import json
import time
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from trainer.domain.materials import (
    build_content,
    editor_allowed,
    material_asset_ids,
    material_payload,
    validate_slug,
)
from trainer.services.material_repository import (
    MaterialActor,
    MaterialAssetStorage,
    MaterialAudit,
    MaterialConflictError,
    MaterialRecord,
    MaterialRepository,
    MaterialRequestData,
    MaterialRequestMetadata,
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


def _normalize(data: MaterialRequestData) -> MaterialRequestData:
    kind = data.kind
    task_number = data.task_number
    try:
        task_number = int(task_number) if task_number is not None else None
        year = int(data.year)
    except (TypeError, ValueError) as error:
        raise ValueError("Проверьте год и номер задания") from error
    if kind == "full":
        task_number = None
    elif kind != "task" or task_number not in {1, 2, 3}:
        raise ValueError("Выберите тип материала и номер задания")
    content = data.content
    if not isinstance(content, dict) or len(json.dumps(content, ensure_ascii=False)) > 150_000:
        raise ValueError("Содержание материала слишком велико")
    title = data.title.strip()
    source = data.source.strip()
    if not 2 <= len(title) <= 120 or not 2 <= len(source) <= 200 or not 2020 <= year <= 2100:
        raise ValueError("Проверьте название, год и источник материала")
    return MaterialRequestData(
        slug=validate_slug(data.slug),
        kind=kind,
        task_number=task_number,
        title=title,
        year=year,
        source=source,
        content=content,
    )


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

    def create(
        self,
        data: MaterialRequestData,
        actor: MaterialActor,
        metadata: MaterialRequestMetadata,
    ) -> dict:
        try:
            normalized = _normalize(data)
        except ValueError as error:
            raise MaterialError("invalid_metadata", str(error)) from error
        now = self._now()
        try:
            with self._repository.transaction() as session:
                material_id = session.create(actor.id, normalized, now)
                session.audit(
                    MaterialAudit(
                        "material_created",
                        actor,
                        metadata,
                        {"materialId": material_id},
                    )
                )
        except MaterialConflictError as error:
            raise MaterialError("slug_exists") from error
        return {"id": normalized.slug, "status": "draft"}

    def update(
        self,
        material_id: str,
        data: MaterialRequestData,
        actor: MaterialActor,
        metadata: MaterialRequestMetadata,
    ) -> dict:
        try:
            normalized = _normalize(data)
        except ValueError as error:
            raise MaterialError("invalid_metadata", str(error)) from error
        try:
            with self._repository.transaction() as session:
                updated = session.update(material_id, actor.id, normalized, self._now())
                if not updated:
                    raise MaterialError("not_found")
        except MaterialConflictError as error:
            raise MaterialError("slug_exists") from error
        return {"id": normalized.slug, "status": "draft"}

    def publish(
        self,
        material_id: str,
        actor: MaterialActor,
        metadata: MaterialRequestMetadata,
    ) -> dict:
        unused_assets = []
        with self._repository.transaction() as session:
            record = session.owned_material(material_id, actor.id)
            if record is None:
                raise MaterialError("not_found")
            try:
                content = build_content(
                    record.kind,
                    record.task_number,
                    json.loads(record.content_json),
                )
                asset_ids = material_asset_ids(content)
            except ValueError as error:
                raise MaterialError("incomplete", str(error)) from error
            if session.owned_asset_ids(record.id, asset_ids) != asset_ids:
                raise MaterialError("foreign_asset")

            assignment_asset_ids = set()
            for snapshot in session.assignment_snapshots():
                try:
                    snapshot_payload = json.loads(snapshot)
                    assignment_asset_ids.update(material_asset_ids(snapshot_payload.get("tasks", {})))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
            retained_asset_ids = asset_ids | assignment_asset_ids
            unused_assets = [asset for asset in session.assets(record.id) if asset.id not in retained_asset_ids]

            now = self._now()
            session.publish(record.id, json.dumps(content, ensure_ascii=False), now)
            session.remove_assets([asset.id for asset in unused_assets])
            session.audit(
                MaterialAudit(
                    "material_published",
                    actor,
                    metadata,
                    {"materialId": record.id},
                )
            )

        for asset in unused_assets:
            with suppress(Exception):
                self._storage.delete(asset.storage_key)
        return {"id": material_id, "status": "published"}

    def archive(self, material_id: str, actor: MaterialActor) -> dict:
        with self._repository.transaction() as session:
            record = session.owned_material(material_id, actor.id)
            if record is None:
                raise MaterialError("not_found")
            session.archive(record.id, self._now())
        return {"ok": True}
