from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ReviewRequestSelection:
    kind: Literal["task", "attempt"]
    tasks: tuple[int, ...]


def validate_review_selection(kind: object, tasks: object) -> ReviewRequestSelection:
    if kind not in {"task", "attempt"}:
        raise ValueError("Некорректный тип запроса на разбор")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Выберите задания для разбора")
    if any(not isinstance(task, int) or isinstance(task, bool) or task not in {1, 2, 3} for task in tasks):
        raise ValueError("Допустимы задания 1–3")
    if len(set(tasks)) != len(tasks):
        raise ValueError("Задания не должны повторяться")
    if kind == "task" and len(tasks) != 1:
        raise ValueError("Для разбора задания выберите ровно одно задание")
    return ReviewRequestSelection(kind=kind, tasks=tuple(sorted(tasks)))


def required_recording_positions(tasks: Iterable[int]) -> set[tuple[int, int | None]]:
    selected = set(tasks)
    required: set[tuple[int, int | None]] = set()
    if 1 in selected:
        required.update((1, question) for question in range(1, 6))
    required.update((task, None) for task in (2, 3) if task in selected)
    return required
