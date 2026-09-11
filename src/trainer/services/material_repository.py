from __future__ import annotations

from collections.abc import Collection, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class MaterialActor:
    id: int
    email: str
    email_verified: bool


@dataclass(frozen=True)
class MaterialRequestMetadata:
    client_ip: str
    user_agent: str


@dataclass(frozen=True)
class MaterialRequestData:
    slug: str
    kind: str
    task_number: int | None
    title: str
    year: int
    source: str
    content: dict


@dataclass(frozen=True)
class MaterialRecord:
    id: int
    slug: str
    owner_id: int
    kind: str
    task_number: int | None
    title: str
    year: int
    source: str
    status: str
    content_json: str


@dataclass(frozen=True)
class MaterialAssetRecord:
    id: int
    material_id: int
    storage_key: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class MaterialAssetAccess:
    storage_key: str
    mime_type: str
    size_bytes: int
    owner_id: int
    material_status: str


@dataclass(frozen=True)
class MaterialAudit:
    action: str
    actor: MaterialActor
    metadata: MaterialRequestMetadata
    details: Mapping[str, object]


class MaterialConflictError(Exception):
    pass


class MaterialImageError(Exception):
    pass


class MaterialAssetStorage(Protocol):
    def put(self, key: str, source: Path, content_type: str) -> None: ...
    def delete(self, key: str) -> None: ...


class MaterialRepositorySession(Protocol):
    def create(self, owner_id: int, data: MaterialRequestData, now: int) -> int: ...

    def update(
        self,
        current_slug: str,
        owner_id: int,
        data: MaterialRequestData,
        now: int,
    ) -> bool: ...

    def owned_material(self, slug: str, owner_id: int) -> MaterialRecord | None: ...

    def owned_asset_ids(self, material_id: int, asset_ids: Collection[int]) -> set[int]: ...

    def assets(self, material_id: int) -> list[MaterialAssetRecord]: ...

    def assignment_snapshots(self) -> list[str]: ...

    def publish(self, material_id: int, content_json: str, now: int) -> None: ...

    def remove_assets(self, asset_ids: Collection[int]) -> None: ...

    def archive(self, material_id: int, now: int) -> None: ...

    def add_asset(
        self,
        material_id: int,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        created_at: int,
    ) -> int: ...

    def audit(self, event: MaterialAudit) -> None: ...


class MaterialRepository(Protocol):
    def published_materials(self) -> list[MaterialRecord]: ...

    def owned_materials(self, owner_id: int) -> list[MaterialRecord]: ...

    def material(self, slug: str) -> MaterialRecord | None: ...

    def owned_material(self, slug: str, owner_id: int) -> MaterialRecord | None: ...

    def asset_access(self, asset_id: int) -> MaterialAssetAccess | None: ...

    def transaction(self) -> AbstractContextManager[MaterialRepositorySession]: ...
