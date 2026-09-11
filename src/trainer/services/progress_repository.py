from dataclasses import dataclass
from typing import Protocol


class ProgressDataError(ValueError):
    pass


@dataclass(frozen=True)
class ProgressRecord:
    document: dict[str, object]
    updated_at: int


class ProgressRepository(Protocol):
    def get(self, user_id: int) -> ProgressRecord | None: ...
    def save(self, user_id: int, document: dict[str, object], updated_at: int) -> None: ...
