from __future__ import annotations

import json
import re

from trainer.domain.accounts import email_in_allowlist

EXAM_SPEC = {
    1: {
        "prepSeconds": 90,
        "answerSeconds": 20,
        "title": "Пять вопросов к объявлению",
    },
    2: {
        "prepSeconds": 120,
        "answerSeconds": 120,
        "title": "Выберите и опишите фотографию",
        "lead": "Вы показываете семейный альбом своему другу. Говорите не более 2 минут (10–12 фраз).",
        "prompts": [
            "когда и где была сделана фотография",
            "кто на ней изображён",
            "почему Вы сделали эту фотографию",
            "почему решили показать другу именно её",
        ],
        "starter": "我选择第 {n} 号照片……",
    },
    3: {
        "prepSeconds": 180,
        "answerSeconds": 180,
        "lead": "Оставьте другу голосовое сообщение: объясните выбор иллюстраций и поделитесь идеями о проекте. Говорите не более 3 минут (12–15 фраз).",
        "prompts": [
            "кратко опишите фотографии и укажите различия",
            "назовите 1–2 достоинства двух вариантов",
            "назовите 1–2 недостатка двух вариантов",
            "скажите, какой вариант Вы предпочитаете и почему",
        ],
    },
}


class MaterialContentValidationError(ValueError):
    pass


_DRAFT_FIELDS = {
    1: ("situation", "banner", "questions", "image", "imageAlt"),
    2: ("images",),
    3: ("title", "images", "imageLabels"),
}


def _draft_text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str or len(value) > maximum:
        raise MaterialContentValidationError(f"Некорректное поле «{label}»")
    return value


def _draft_list(value: object, label: str, length: int, maximum: int) -> list[str]:
    if type(value) is not list or len(value) != length:
        raise MaterialContentValidationError(f"Некорректное поле «{label}»")
    return [_draft_text(item, label, maximum) for item in value]


def _draft_task(number: int, raw: object) -> dict:
    if type(raw) is not dict or set(raw) != set(_DRAFT_FIELDS[number]):
        raise MaterialContentValidationError(f"Некорректное содержание задания {number}")
    if number == 1:
        return {
            "situation": _draft_text(raw["situation"], "Ситуация", 1500),
            "banner": _draft_text(raw["banner"], "Объявление", 300),
            "questions": _draft_list(raw["questions"], "Вопросы", 5, 300),
            "image": _draft_text(raw["image"], "Изображение", 500),
            "imageAlt": _draft_text(raw["imageAlt"], "Описание изображения", 300),
        }
    if number == 2:
        return {"images": _draft_list(raw["images"], "Изображения", 3, 500)}
    return {
        "title": _draft_text(raw["title"], "Название проекта", 150),
        "images": _draft_list(raw["images"], "Изображения", 2, 500),
        "imageLabels": _draft_list(raw["imageLabels"], "Подписи", 2, 100),
    }


def normalize_material_draft_content(
    kind: str,
    task_number: int | None,
    raw: object,
) -> dict[str, dict]:
    if type(raw) is not dict:
        raise MaterialContentValidationError("Некорректное содержание материала")
    if kind == "full":
        if task_number is not None or set(raw) != {"1", "2", "3"}:
            raise MaterialContentValidationError("Содержание не соответствует типу материала")
        numbers = (1, 2, 3)
    elif kind == "task" and task_number in {1, 2, 3} and set(raw) == {str(task_number)}:
        numbers = (task_number,)
    else:
        raise MaterialContentValidationError("Содержание не соответствует выбранному заданию")
    return {str(number): _draft_task(number, raw[str(number)]) for number in numbers}


def editor_allowed(user: dict | None, editor_emails: str) -> bool:
    if not user or not user.get("emailVerified"):
        return False
    return email_in_allowlist(user["email"], editor_emails)


def validate_slug(value: str) -> str:
    slug = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9-]{3,50}", slug) or slug.startswith(("demo-", "open-")):
        raise ValueError("Идентификатор должен содержать латинские буквы, цифры и дефисы")
    return slug


def _text(value: object, label: str, minimum: int = 2, maximum: int = 1000) -> str:
    result = str(value or "").strip()
    if not minimum <= len(result) <= maximum:
        raise ValueError(f"Поле «{label}» должно содержать от {minimum} до {maximum} символов")
    return result


def _images(value: object, expected: int) -> list[str]:
    if not isinstance(value, list) or len(value) != expected:
        raise ValueError(f"Необходимо добавить изображений: {expected}")
    return [_text(item, "Изображение", 4, 500) for item in value]


def build_task(task_number: int, raw: object) -> dict:
    if task_number not in EXAM_SPEC or not isinstance(raw, dict):
        raise ValueError("Некорректное содержание задания")
    fixed = dict(EXAM_SPEC[task_number])
    if task_number == 1:
        questions = raw.get("questions")
        if not isinstance(questions, list) or len(questions) != 5:
            raise ValueError("В задании 1 должно быть ровно пять вопросов")
        return {
            **fixed,
            "situation": _text(raw.get("situation"), "Ситуация", 10, 1500),
            "banner": _text(raw.get("banner"), "Объявление", 2, 300),
            "questions": [_text(question, f"Вопрос {index}", 2, 300) for index, question in enumerate(questions, 1)],
            "image": _text(raw.get("image"), "Изображение", 4, 500),
            "imageAlt": _text(raw.get("imageAlt"), "Описание изображения", 2, 300),
        }
    if task_number == 2:
        return {**fixed, "images": _images(raw.get("images"), 3)}
    labels = raw.get("imageLabels")
    if not isinstance(labels, list) or len(labels) != 2:
        raise ValueError("В задании 3 должно быть ровно две подписи")
    return {
        **fixed,
        "title": _text(raw.get("title"), "Название проекта", 4, 150),
        "images": _images(raw.get("images"), 2),
        "imageLabels": [_text(label, f"Подпись {index}", 2, 100) for index, label in enumerate(labels, 1)],
    }


def material_asset_ids(content: dict[str, dict]) -> set[int]:
    urls: list[str] = []
    for task in content.values():
        if task.get("image"):
            urls.append(task["image"])
        urls.extend(task.get("images") or [])
    ids = set()
    for url in urls:
        match = re.fullmatch(r"/api/material-assets/(\d+)", url)
        if not match:
            raise ValueError("Используйте изображения, загруженные через редактор")
        ids.add(int(match.group(1)))
    return ids


def build_content(kind: str, task_number: int | None, raw: object) -> dict[str, dict]:
    if not isinstance(raw, dict):
        raise ValueError("Некорректное содержание материала")
    if kind == "task":
        if task_number not in {1, 2, 3}:
            raise ValueError("Выберите номер задания")
        return {str(task_number): build_task(task_number, raw.get(str(task_number), raw))}
    if kind != "full":
        raise ValueError("Неизвестный тип материала")
    return {str(number): build_task(number, raw.get(str(number))) for number in (1, 2, 3)}


def material_payload(row: dict) -> dict:
    tasks = json.loads(row["content_json"])
    return {
        "id": row["slug"],
        "year": row["year"],
        "label": row["title"],
        "source": row["source"],
        "totalMinutes": 14 if row["kind"] == "full" else {1: 4, 2: 4, 3: 6}[row["task_number"]],
        "kind": row["kind"],
        "taskNumber": row["task_number"],
        "official": False,
        "status": row["status"],
        "tasks": tasks,
    }
