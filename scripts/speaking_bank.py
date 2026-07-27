from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass

SPEAKING_NUMBERS = (30, 31, 32)

_BLOCK_SPLIT = re.compile(r"^(?=# Блок: задание )", re.MULTILINE)
_BLOCK_NUMBER = re.compile(r"^# Блок: задание (\d+)")
_IMAGE_LINE = re.compile(r"^\d+\.\s+(media/\S+)$", re.MULTILINE)
_TASK_SECTION = "## Задание"

_CJK_RUN = re.compile(r"[　-〿一-鿿！-￯]+")
_NUMBERED_ITEM = re.compile(r"\s*\d[.)]\s*")
_QUESTION_TAIL = re.compile(r"\.?\s*На каждый вопрос отводится.*$")
_SITUATION = re.compile(r"(Вы\s+увидели[^.]*\.)")
_QUESTIONS_MARKER = "следующую информацию:"
_MIN_BANNER_LENGTH = 2

_THEME = re.compile(r"на тему\s+«([^»]+)»")
_READY_MARKER = re.compile(r"\s*Через 3 минуты будьте готовы:\s*$")
_PROMPT_TAIL = re.compile(r"\.?\s*У Вас есть 3 минуты на подготовку.*$")
_BULLET = "·"
PROJECT_TIMING = "Говорите не более 3 минут (12–15 фраз)."

_PUNCTUATION = re.compile(r"[\s!。.,、;：?()«»\"'\-—–]+")


@dataclass(frozen=True)
class Block:
    """Блок банка: номер задания, пути к фотографиям стимула и текст формулировки."""

    number: int
    images: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Announcement:
    """Содержательная часть задания 30: ситуация, китайское объявление и пять пунктов."""

    situation: str
    banner: str
    questions: tuple[str, ...]


@dataclass(frozen=True)
class VariantSource:
    """Комплект блоков на один вариант: задания 30, 31 и 32."""

    announcement: Block
    album: Block
    project: Block


@dataclass(frozen=True)
class Project:
    """Содержательная часть задания 32: тема проекта, вводная и четыре пункта."""

    theme: str
    lead: str
    prompts: tuple[str, ...]


def parse_blocks(source: str) -> list[Block]:
    """Разбирает файл банка, оставляя только блоки устной части."""
    blocks: list[Block] = []
    for chunk in _BLOCK_SPLIT.split(source):
        header = _BLOCK_NUMBER.match(chunk)
        if not header or int(header.group(1)) not in SPEAKING_NUMBERS:
            continue
        stimulus, _, task = chunk.partition(_TASK_SECTION)
        blocks.append(
            Block(
                number=int(header.group(1)),
                images=tuple(_IMAGE_LINE.findall(stimulus)),
                text=" ".join(task.split()),
            )
        )
    return blocks


def parse_announcement(text: str) -> Announcement | None:
    """Разбирает задание 30. Возвращает None, если баннер утрачен или пунктов не пять."""
    runs = [run.strip() for run in _CJK_RUN.findall(text)]
    banner = max(runs, key=len, default="")
    situation = _SITUATION.search(text)
    _, _, tail = text.partition(_QUESTIONS_MARKER)
    questions = tuple(
        _QUESTION_TAIL.sub("", item.strip(" ;.·")).strip(" ;.") for item in _NUMBERED_ITEM.split(tail)[1:]
    )
    if len(banner) < _MIN_BANNER_LENGTH or not situation or len(questions) != 5 or not all(questions):
        return None
    return Announcement(situation=situation.group(1), banner=banner, questions=questions)


def parse_project(text: str) -> Project | None:
    """Разбирает задание 32. Возвращает None, если темы нет или пунктов не четыре."""
    head, _, rest = text.partition(_BULLET)
    theme = _THEME.search(head)
    prompts = tuple(_PROMPT_TAIL.sub("", item.strip(" ;.·")).strip(" ;.") for item in rest.split(_BULLET))
    if not theme or len(prompts) != 4 or not all(prompts):
        return None
    lead = _READY_MARKER.sub("", head.strip())
    return Project(theme=theme.group(1), lead=f"{lead} {PROJECT_TIMING}", prompts=prompts)


def normalize(value: str) -> str:
    """Приводит строку к ключу сравнения: NFKC, нижний регистр, без пробелов, пунктуации и различия ё/е.

    Свести ё к е обязательно: в банке тема «Волонтерская деятельность», в demo-2025 — «Волонтёрская
    деятельность». NFKC эти строки не сближает, и повтор прошёл бы в каталог.
    """
    folded = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return _PUNCTUATION.sub("", folded)


def _distinct_photos(block: Block, photo_key: Callable[[str], str]) -> set[str] | None:
    keys = {photo_key(image) for image in block.images}
    return keys if len(keys) == len(block.images) else None


def _unique_announcements(
    blocks: Sequence[Block],
    photo_key: Callable[[str], str],
    used_banners: frozenset[str],
    used_questions: frozenset[str],
) -> list[Block]:
    selected: list[Block] = []
    seen: set[tuple[str, str]] = set()
    for block in blocks:
        if block.number != 30 or _distinct_photos(block, photo_key) is None:
            continue
        parsed = parse_announcement(block.text)
        if parsed is None:
            continue
        banner, questions = normalize(parsed.banner), normalize("|".join(parsed.questions))
        if (banner, questions) in seen or banner in used_banners or questions in used_questions:
            continue
        seen.add((banner, questions))
        selected.append(block)
    return selected


def _unique_albums(blocks: Sequence[Block], photo_key: Callable[[str], str]) -> list[Block]:
    selected: list[Block] = []
    seen: set[tuple[str, ...]] = set()
    for block in blocks:
        keys = _distinct_photos(block, photo_key) if block.number == 31 else None
        if keys is None or len(block.images) != 3:
            continue
        signature = tuple(sorted(keys))
        if signature in seen:
            continue
        seen.add(signature)
        selected.append(block)
    return selected


def _unique_projects(
    blocks: Sequence[Block],
    photo_key: Callable[[str], str],
    used_themes: frozenset[str],
) -> list[Block]:
    selected: list[Block] = []
    seen: set[str] = set()
    for block in blocks:
        if block.number != 32 or _distinct_photos(block, photo_key) is None:
            continue
        parsed = parse_project(block.text)
        if parsed is None:
            continue
        theme = normalize(parsed.theme)
        if theme in seen or theme in used_themes:
            continue
        seen.add(theme)
        selected.append(block)
    return selected


def _take_disjoint(pool: list[Block], taken: set[str], photo_key: Callable[[str], str]) -> Block | None:
    for index, block in enumerate(pool):
        keys = {photo_key(image) for image in block.images}
        if not keys & taken:
            return pool.pop(index)
    return None


def select_sources(
    blocks: Sequence[Block],
    *,
    photo_key: Callable[[str], str],
    used_banners: frozenset[str] = frozenset(),
    used_questions: frozenset[str] = frozenset(),
    used_themes: frozenset[str] = frozenset(),
) -> list[VariantSource]:
    """Собирает комплекты 30+31+32 без повторов заданий и без повторов фотографий внутри варианта.

    Задание 30, которому не нашлось непересекающейся пары, пропускается, а не обрывает отбор:
    иначе одно неудачное сочетание отбросило бы весь оставшийся хвост банка.
    """
    announcements = _unique_announcements(blocks, photo_key, used_banners, used_questions)
    albums = _unique_albums(blocks, photo_key)
    projects = _unique_projects(blocks, photo_key, used_themes)
    sources: list[VariantSource] = []
    for announcement in announcements:
        taken = {photo_key(image) for image in announcement.images}
        album = _take_disjoint(albums, taken, photo_key)
        if album is None:
            continue
        taken |= {photo_key(image) for image in album.images}
        project = _take_disjoint(projects, taken, photo_key)
        if project is None:
            albums.append(album)
            continue
        sources.append(VariantSource(announcement=announcement, album=album, project=project))
    return sources
