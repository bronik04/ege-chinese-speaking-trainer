from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ReviewActor:
    id: int
    email: str


@dataclass(frozen=True)
class RequestMetadata:
    client_ip: str
    user_agent: str


@dataclass(frozen=True)
class MaterialAsset:
    storage_key: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class UploadTarget:
    item_id: int
    status: str


@dataclass(frozen=True)
class RecordingRow:
    id: int
    storage_key: str


@dataclass(frozen=True)
class RequestItem:
    id: int
    task: int


class ReviewAssetRegistry(Protocol):
    def material_asset(self, asset_id: int) -> MaterialAsset | None: ...

    def add_review_asset(
        self,
        request_id: int,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        created_at: int,
    ) -> int: ...

    def remove_review_asset(self, asset_id: int) -> None: ...


class ReviewRequestSession(ReviewAssetRegistry, Protocol):
    def published_material(self, slug: str) -> dict | None: ...

    def create_request(self, student_id: int, kind: str, variant_id: str, run_json: str) -> int: ...

    def add_item(self, request_id: int, task: int, snapshot_json: str) -> int: ...

    def audit(
        self,
        action: str,
        *,
        actor: ReviewActor,
        metadata: RequestMetadata,
        details: Mapping[str, object],
    ) -> None: ...

    def upload_target(self, request_id: int, student_id: int, task: int) -> UploadTarget | None: ...

    def guard_uploading(self, request_id: int, student_id: int) -> bool: ...

    def recordings_at(self, item_id: int, question: int | None) -> list[RecordingRow]: ...

    def remove_recordings_at(self, item_id: int, question: int | None) -> None: ...

    def add_recording(
        self,
        *,
        item_id: int,
        question: int | None,
        label: str,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        duration_seconds: float,
        created_at: int,
        expires_at: int,
    ) -> int: ...

    def enqueue_cleanup(
        self,
        *,
        audio_keys: Sequence[str] = (),
        assignment_keys: Sequence[str] = (),
    ) -> None: ...

    def request_status(self, request_id: int, student_id: int) -> str | None: ...

    def request_items(self, request_id: int) -> list[RequestItem]: ...

    def uploaded_positions(self, request_id: int) -> set[tuple[int, int | None]]: ...

    def queue_request(self, request_id: int, student_id: int, submitted_at: int) -> bool: ...

    def request_storage_keys(self, request_id: int) -> tuple[list[str], list[str]]: ...

    def delete_request(self, request_id: int, student_id: int) -> bool: ...

    def scorable_items(self, request_id: int) -> list[RequestItem] | None: ...

    def save_item_scores(self, item_id: int, scores_json: str, total: int, maximum: int) -> None: ...

    def mark_reviewed(self, request_id: int, reviewer_id: int, reviewed_at: int) -> None: ...


class ReviewRequestRepository(Protocol):
    def transaction(self, *, immediate: bool = False) -> AbstractContextManager[ReviewRequestSession]: ...

    def student_requests(self, student_id: int) -> list[dict]: ...

    def teacher_requests(
        self,
        *,
        student: str = "",
        task: int | None = None,
        status: str = "",
        submitted_from: int | None = None,
        submitted_before: int | None = None,
    ) -> list[dict]: ...

    def teacher_detail(self, request_id: int) -> dict | None: ...

    def enqueue_orphan_cleanup(
        self,
        *,
        audio_keys: Sequence[str] = (),
        assignment_keys: Sequence[str] = (),
    ) -> None: ...

    def process_cleanup(self) -> None: ...
