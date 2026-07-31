from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestContext:
    """Данные запроса, нужные действиям для аудита и писем."""

    client_ip: str
    user_agent: str


@dataclass
class ActionResult:
    """Результат действия: тело ответа и то, что маршрут должен добавить к нему."""

    payload: dict
    status: int = 200
    session_token: str | None = None
    clear_session: bool = False
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FileResult:
    """Ссылка на файл в хранилище; чтение выполняет маршрут."""

    key: str
    mime_type: str
    size_bytes: int
