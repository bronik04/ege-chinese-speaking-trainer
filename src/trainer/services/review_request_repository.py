from __future__ import annotations

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


class ReviewRequestRepository(Protocol):
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
