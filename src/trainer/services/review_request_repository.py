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
