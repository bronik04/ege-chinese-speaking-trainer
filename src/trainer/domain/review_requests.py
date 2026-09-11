from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from trainer.domain.progress import CompletedProgressRun, ProgressValidationError, parse_completed_run


@dataclass(frozen=True)
class ReviewRequestSelection:
    kind: Literal["task", "attempt"]
    tasks: tuple[int, ...]


@dataclass(frozen=True)
class ValidatedReviewRequest:
    selection: ReviewRequestSelection
    run: CompletedProgressRun


def validate_review_selection(kind: object, tasks: object) -> ReviewRequestSelection:
    if not isinstance(kind, str) or kind not in {"task", "attempt"}:
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


def validate_review_request(
    kind: object,
    tasks: object,
    variant_id: object,
    run: object,
) -> ValidatedReviewRequest:
    selection = validate_review_selection(kind, tasks)
    try:
        completed_run = parse_completed_run(run)
    except ProgressValidationError as error:
        raise ValueError("Некорректные данные попытки") from error
    if completed_run.status != "completed":
        raise ValueError("Для разбора можно отправить только завершённую попытку")
    if completed_run.variant_id != variant_id:
        raise ValueError("Вариант попытки не совпадает с выбранным вариантом")
    if not set(selection.tasks).issubset(completed_run.completed_tasks):
        raise ValueError("Выбранные задания отсутствуют среди завершённых")
    return ValidatedReviewRequest(selection, completed_run)


def required_recording_positions(tasks: Iterable[int]) -> set[tuple[int, int | None]]:
    selected = set(tasks)
    required: set[tuple[int, int | None]] = set()
    if 1 in selected:
        required.update((1, question) for question in range(1, 6))
    required.update((task, None) for task in (2, 3) if task in selected)
    return required
