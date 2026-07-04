from __future__ import annotations

CRITERIA = {
    1: {f"question{number}": 1 for number in range(1, 6)},
    2: {"content": 3, "organization": 2, "language": 2},
    3: {"content": 3, "organization": 2, "language": 3},
}


def validate_scores(raw_scores: object, tasks: list[int]) -> tuple[dict, int, int]:
    if not isinstance(raw_scores, dict):
        raise ValueError("Некорректные баллы")
    normalized: dict[str, dict[str, int]] = {}
    total = 0
    maximum = 0
    for task in tasks:
        definition = CRITERIA[task]
        supplied = raw_scores.get(str(task), {})
        if not isinstance(supplied, dict):
            raise ValueError(f"Некорректные баллы за задание {task}")
        task_scores = {}
        for key, max_score in definition.items():
            value = supplied.get(key, 0)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= max_score:
                raise ValueError(f"Баллы за задание {task} выходят за допустимый диапазон")
            task_scores[key] = value
        if task in {2, 3} and task_scores["content"] == 0:
            task_scores["organization"] = 0
            task_scores["language"] = 0
        normalized[str(task)] = task_scores
        total += sum(task_scores.values())
        maximum += sum(definition.values())
    return normalized, total, maximum
