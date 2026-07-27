# Импорт устных заданий из банка ЕГЭ — план реализации

> **Для агентов:** ОБЯЗАТЕЛЬНЫЙ СУБ-СКИЛЛ: используйте superpowers:subagent-driven-development
> (рекомендуется) или superpowers:executing-plans, чтобы выполнять план задача за задачей.
> Шаги отмечены чекбоксами (`- [ ]`).

**Цель:** добавить в каталог тренажёра 27 вариантов устной части, собранных из блоков открытого банка ФИПИ,
без повторов внутри партии и относительно семи уже загруженных вариантов.

**Архитектура:** чистый модуль `scripts/speaking_bank.py` разбирает текст банка и отбирает комплекты
(зад. 30 + 31 + 32), не касаясь файловой системы; `scripts/import_speaking_bank.py` добавляет ввод-вывод —
перцептивные хэши фотографий, контактные листы, конвертацию в webp и запись контента. Схема
`schemas/variant.schema.json`, модель данных и API не меняются.

**Стек:** Python 3.12, Pillow 12.3.0 (уже в `requirements.txt`), `unittest`, ruff, Node `node --test`
для фронтенда.

## Общие ограничения

- Спецификация: [docs/superpowers/specs/2026-07-27-speaking-bank-import-design.md](../specs/2026-07-27-speaking-bank-import-design.md).
- Работать в ветке `feature/speaking-bank-import` (текущая ветка — `agent/fix-review-findings`).
- **Коммит и отправку изменений выполнять только после явного разрешения владельца проекта**
  (CONTRIBUTING.md). Шаги «Коммит» в плане описывают, что и когда фиксировать, но выполняются
  после разрешения.
- Python: ruff `line-length = 120`, двойные кавычки, `from __future__ import annotations` первой строкой,
  тесты — `unittest.TestCase`, а не pytest.
- Комментарии, docstring'и, сообщения коммитов и пользовательские строки — на русском.
- Банк лежит вне репозитория: `/Users/bronik04/Yandex.Disk.localized/Китайский язык/03-Экзамены/ЕГЭ/!Банк заданий ЕГЭ/1_Импорт_в_программу`.
  Ни один файл банка в репозиторий не копируется, путь передаётся аргументом `--bank`.
- Новые зависимости не добавляются.
- Значения, зафиксированные спецификацией: 27 вариантов, `id` = `bank-01`…`bank-27`, `year` = 2026,
  `label` = «Банк ФИПИ · вариант NN», `source` = «ФИПИ · открытый банк заданий», `totalMinutes` = 14,
  порог совпадения фотографий — расстояние Хэмминга ≤ 4 по dhash 8×8.

---

## Структура файлов

| Файл | Ответственность |
| --- | --- |
| `scripts/speaking_bank.py` | создаётся; чистые функции: разбор блоков банка, разбор заданий 30 и 32, нормализация ключей, отбор комплектов без повторов. Без файловой системы, без Pillow |
| `scripts/import_speaking_bank.py` | создаётся; CLI `plan` и `build`: хэши фотографий, контактные листы, конвертация в webp, запись вариантов и `index.json` |
| `tests/unit/test_speaking_bank.py` | создаётся; тесты чистого модуля на встроенных образцах текста |
| `tests/unit/test_speaking_bank_import.py` | создаётся; тесты ввода-вывода на синтетическом банке во временном каталоге |
| `frontend/js/catalog/variant-catalog.js` | правится `variantKind()` — третья ветка для `bank-*` |
| `tests-js/unit/views.test.js` | дополняется проверка `variantKind("bank-01")` |
| `content/variants/bank-01.json` … `bank-27.json` | результат работы `build` |
| `content/variants/index.json` | дополняется 27 записями |
| `public/assets/variants/bank-01/` … `bank-27/` | по 6 файлов `candidate-NN.webp` |

---

### Задача 1: разбор блоков банка

**Файлы:**
- Создать: `scripts/speaking_bank.py`
- Тест: `tests/unit/test_speaking_bank.py`

**Интерфейсы:**
- Использует: ничего.
- Отдаёт: `SPEAKING_NUMBERS: tuple[int, ...]`, `@dataclass(frozen=True) Block(number: int, images: tuple[str, ...], text: str)`,
  `parse_blocks(source: str) -> list[Block]`.

- [ ] **Шаг 1: написать падающий тест**

`tests/unit/test_speaking_bank.py`:

```python
from __future__ import annotations

import unittest

from scripts.speaking_bank import Block, parse_blocks

BANK_SAMPLE = """# Блок: задание 30
теги: Банк ФИПИ
## Стимул
1. media/photos/p1_t03_img2.jpg

## Задание
Ознакомьтесь с объявлением. Вы увидели объявление о курсах и решили получить дополнительную информацию.

# Блок: задание 27
теги: Банк ФИПИ

## Задание
стем: 请选择 ___ 。

# Блок: задание 31
теги: Банк ФИПИ
## Стимул
1. media/photos/p9_t08_img1.jpg
2. media/photos/p9_t08_img2.jpg
3. media/photos/p9_t08_img3.jpg

## Задание
Вы показываете семейный альбом своему другу.
"""


class ParseBlocksTest(unittest.TestCase):
    def test_keeps_only_speaking_blocks(self):
        blocks = parse_blocks(BANK_SAMPLE)

        self.assertEqual([block.number for block in blocks], [30, 31])

    def test_collects_stimulus_images_in_order(self):
        blocks = parse_blocks(BANK_SAMPLE)

        self.assertEqual(blocks[0].images, ("media/photos/p1_t03_img2.jpg",))
        self.assertEqual(
            blocks[1].images,
            ("media/photos/p9_t08_img1.jpg", "media/photos/p9_t08_img2.jpg", "media/photos/p9_t08_img3.jpg"),
        )

    def test_task_text_is_collapsed_to_one_line(self):
        blocks = parse_blocks(BANK_SAMPLE)

        self.assertEqual(blocks[1].text, "Вы показываете семейный альбом своему другу.")

    def test_block_is_hashable_and_frozen(self):
        block = Block(number=30, images=("a.jpg",), text="текст")

        with self.assertRaises(AttributeError):
            block.number = 31


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Шаг 2: убедиться, что тест падает**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank -v`
Ожидается: `ModuleNotFoundError: No module named 'scripts.speaking_bank'`

- [ ] **Шаг 3: минимальная реализация**

`scripts/speaking_bank.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass

SPEAKING_NUMBERS = (30, 31, 32)

_BLOCK_SPLIT = re.compile(r"^(?=# Блок: задание )", re.MULTILINE)
_BLOCK_NUMBER = re.compile(r"^# Блок: задание (\d+)")
_IMAGE_LINE = re.compile(r"^\d+\.\s+(media/\S+)$", re.MULTILINE)
_TASK_SECTION = "## Задание"


@dataclass(frozen=True)
class Block:
    """Блок банка: номер задания, пути к фотографиям стимула и текст формулировки."""

    number: int
    images: tuple[str, ...]
    text: str


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
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank -v`
Ожидается: `OK`, 4 теста.

- [ ] **Шаг 5: коммит**

```bash
git add scripts/speaking_bank.py tests/unit/test_speaking_bank.py
git commit -m "Добавить разбор блоков устной части банка ЕГЭ"
```

---

### Задача 2: разбор задания 30

**Файлы:**
- Изменить: `scripts/speaking_bank.py`
- Тест: `tests/unit/test_speaking_bank.py`

**Интерфейсы:**
- Использует: `Block` из задачи 1.
- Отдаёт: `@dataclass(frozen=True) Announcement(situation: str, banner: str, questions: tuple[str, ...])`,
  `parse_announcement(text: str) -> Announcement | None`. Возвращает `None`, если баннер отсутствует
  или пунктов не ровно пять.

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/unit/test_speaking_bank.py` (импорт дополнить: `from scripts.speaking_bank import Announcement, Block, parse_announcement, parse_blocks`):

```python
ANNOUNCEMENT_ROUND = (
    "Задание 1. Ознакомьтесь с объявлением: Вы увидели рекламное объявление об интересной экскурсии "
    "и решили получить дополнительную информацию. У Вас есть 1,5 минуты на подготовку. Затем за 1,5 минуты "
    "Вам нужно задать 5 вопросов, чтобы получить следующую информацию: 精彩的旅游路线，等你来！ "
    "1) достопримечательности по маршруту; 2) стоимость билета; 3) дата экскурсии; "
    "4) количество человек в группе; 5) длительность экскурсии."
)

ANNOUNCEMENT_DOTTED = (
    "Ознакомьтесь с объявлением. 篮球班正在招生！ Вы увидели рекламное объявление о наборе ребят "
    "в баскетбольную секцию и решили получить дополнительную информацию. У Вас есть 1,5 минуты на подготовку. "
    "Затем за 1,5 минуты Вам нужно задать 5 вопросов, чтобы получить следующую информацию: "
    "1. местоположение; 2. группы для начинающих; 3. расписание; 4. наличие раздевалки; 5. наличие душа."
)

ANNOUNCEMENT_TIMING_TAIL = (
    "Ознакомьтесь с объявлением. Вы увидели объявление о курсах ботаники и решили получить дополнительную "
    "информацию. У Вас есть 1,5 минуты на подготовку. Затем Вам нужно задать 5 вопросов, чтобы получить "
    "следующую информацию: 欢迎你们加入植物学培训班 1) адрес; 2) расписание занятий; 3) стоимость занятий "
    "за месяц; 4) продолжительность одного занятия; 5) количество занятий в неделю. "
    "На каждый вопрос отводится 20 секунд."
)

ANNOUNCEMENT_WITHOUT_BANNER = (
    "Задание 1. Ознакомьтесь с объявлением: Вы увидели рекламное объявление о волейбольном клубе и решили "
    "получить дополнительную информацию. У Вас есть 1,5 минуты на подготовку. Затем за 1,5 минуты Вам нужно "
    "задать 5 вопросов, чтобы получить следующую информацию: ! 1) адрес клуба; 2) количество спортсменов "
    "в клубе; 3) плата за обучение; 4) планируемые соревнования; 5) спортивная форма."
)


class ParseAnnouncementTest(unittest.TestCase):
    def test_parses_banner_situation_and_five_questions(self):
        parsed = parse_announcement(ANNOUNCEMENT_ROUND)

        self.assertEqual(parsed.banner, "精彩的旅游路线，等你来！")
        self.assertEqual(
            parsed.situation,
            "Вы увидели рекламное объявление об интересной экскурсии и решили получить дополнительную информацию.",
        )
        self.assertEqual(parsed.questions[0], "достопримечательности по маршруту")
        self.assertEqual(parsed.questions[4], "длительность экскурсии")

    def test_accepts_dotted_numbering_and_banner_before_situation(self):
        parsed = parse_announcement(ANNOUNCEMENT_DOTTED)

        self.assertEqual(parsed.banner, "篮球班正在招生！")
        self.assertEqual(len(parsed.questions), 5)
        self.assertEqual(parsed.questions[3], "наличие раздевалки")

    def test_drops_the_per_question_timing_tail(self):
        parsed = parse_announcement(ANNOUNCEMENT_TIMING_TAIL)

        self.assertEqual(parsed.questions[4], "количество занятий в неделю")

    def test_rejects_block_without_chinese_banner(self):
        self.assertIsNone(parse_announcement(ANNOUNCEMENT_WITHOUT_BANNER))
```

- [ ] **Шаг 2: убедиться, что тест падает**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank -v`
Ожидается: `ImportError: cannot import name 'parse_announcement'`

- [ ] **Шаг 3: минимальная реализация**

Дописать в `scripts/speaking_bank.py`:

```python
_CJK_RUN = re.compile(r"[　-〿一-鿿！-￯]+")
_NUMBERED_ITEM = re.compile(r"\s*\d[.)]\s*")
_QUESTION_TAIL = re.compile(r"\.?\s*На каждый вопрос отводится.*$")
_SITUATION = re.compile(r"(Вы\s+увидели[^.]*\.)")
_QUESTIONS_MARKER = "следующую информацию:"
_MIN_BANNER_LENGTH = 2


@dataclass(frozen=True)
class Announcement:
    """Содержательная часть задания 30: ситуация, китайское объявление и пять пунктов."""

    situation: str
    banner: str
    questions: tuple[str, ...]


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
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank -v`
Ожидается: `OK`, 8 тестов.

- [ ] **Шаг 5: коммит**

```bash
git add scripts/speaking_bank.py tests/unit/test_speaking_bank.py
git commit -m "Разбирать задание 30 из блока банка"
```

---

### Задача 3: разбор задания 32

**Файлы:**
- Изменить: `scripts/speaking_bank.py`
- Тест: `tests/unit/test_speaking_bank.py`

**Интерфейсы:**
- Использует: ничего из предыдущих задач.
- Отдаёт: `@dataclass(frozen=True) Project(theme: str, lead: str, prompts: tuple[str, ...])`,
  `parse_project(text: str) -> Project | None`. `lead` заканчивается фразой
  «Говорите не более 3 минут (12–15 фраз).», `prompts` — ровно четыре пункта.

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/unit/test_speaking_bank.py` (импорт дополнить `Project, parse_project`):

```python
PROJECT_SAMPLE = (
    "Вы выполняете вместе с другом проектную работу на тему «Времена года». Вы нашли фотографии для "
    "иллюстрации проекта, но по техническим причинам не можете сейчас переслать их другу. Оставьте ему "
    "голосовое сообщение: объясните свой выбор фотографий и поделитесь некоторыми идеями о проекте. "
    "Через 3 минуты будьте готовы: · объяснить выбор иллюстраций для проектной работы, кратко описав их "
    "и указав различия; · указать достоинства (1–2) двух времён года; · указать недостатки (1–2) двух "
    "времён года; · выразить Ваше мнение по теме проектной работы – какое время года Вы предпочитаете "
    "и почему. У Вас есть 3 минуты на подготовку. Говорить следует не более 3 минут (12–15 фраз). "
    "Фотография 1 Фотография 2"
)

PROJECT_WITHOUT_BULLETS = (
    "Вы выполняете вместе с другом проектную работу на тему «Досуг». Оставьте ему голосовое сообщение."
)


class ParseProjectTest(unittest.TestCase):
    def test_extracts_theme(self):
        parsed = parse_project(PROJECT_SAMPLE)

        self.assertEqual(parsed.theme, "Времена года")

    def test_lead_drops_the_ready_marker_and_gets_project_timing(self):
        parsed = parse_project(PROJECT_SAMPLE)

        self.assertTrue(parsed.lead.startswith("Вы выполняете вместе с другом проектную работу"))
        self.assertNotIn("Через 3 минуты будьте готовы", parsed.lead)
        self.assertTrue(parsed.lead.endswith("Говорите не более 3 минут (12–15 фраз)."))

    def test_keeps_four_thematic_prompts_without_the_timing_tail(self):
        parsed = parse_project(PROJECT_SAMPLE)

        self.assertEqual(len(parsed.prompts), 4)
        self.assertEqual(parsed.prompts[1], "указать достоинства (1–2) двух времён года")
        self.assertEqual(
            parsed.prompts[3],
            "выразить Ваше мнение по теме проектной работы – какое время года Вы предпочитаете и почему",
        )

    def test_rejects_block_without_bullets(self):
        self.assertIsNone(parse_project(PROJECT_WITHOUT_BULLETS))
```

- [ ] **Шаг 2: убедиться, что тест падает**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank -v`
Ожидается: `ImportError: cannot import name 'parse_project'`

- [ ] **Шаг 3: минимальная реализация**

Дописать в `scripts/speaking_bank.py`:

```python
_THEME = re.compile(r"на тему\s+«([^»]+)»")
_READY_MARKER = re.compile(r"\s*Через 3 минуты будьте готовы:\s*$")
_PROMPT_TAIL = re.compile(r"\.?\s*У Вас есть 3 минуты на подготовку.*$")
_BULLET = "·"
PROJECT_TIMING = "Говорите не более 3 минут (12–15 фраз)."


@dataclass(frozen=True)
class Project:
    """Содержательная часть задания 32: тема проекта, вводная и четыре пункта."""

    theme: str
    lead: str
    prompts: tuple[str, ...]


def parse_project(text: str) -> Project | None:
    """Разбирает задание 32. Возвращает None, если темы нет или пунктов не четыре."""
    head, _, rest = text.partition(_BULLET)
    theme = _THEME.search(head)
    prompts = tuple(_PROMPT_TAIL.sub("", item.strip(" ;.·")).strip(" ;.") for item in rest.split(_BULLET))
    if not theme or len(prompts) != 4 or not all(prompts):
        return None
    lead = _READY_MARKER.sub("", head.strip())
    return Project(theme=theme.group(1), lead=f"{lead} {PROJECT_TIMING}", prompts=prompts)
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank -v`
Ожидается: `OK`, 12 тестов.

- [ ] **Шаг 5: коммит**

```bash
git add scripts/speaking_bank.py tests/unit/test_speaking_bank.py
git commit -m "Разбирать задание 32 из блока банка"
```

---

### Задача 4: отбор комплектов без повторов

**Файлы:**
- Изменить: `scripts/speaking_bank.py`
- Тест: `tests/unit/test_speaking_bank.py`

**Интерфейсы:**
- Использует: `Block`, `parse_announcement`, `parse_project` из задач 1–3.
- Отдаёт: `normalize(value: str) -> str`,
  `@dataclass(frozen=True) VariantSource(announcement: Block, album: Block, project: Block)`,
  `select_sources(blocks: Sequence[Block], *, photo_key: Callable[[str], str], used_banners: frozenset[str] = frozenset(), used_questions: frozenset[str] = frozenset(), used_themes: frozenset[str] = frozenset()) -> list[VariantSource]`.

  `photo_key` превращает путь к фотографии в её каноническое имя: одинаковые снимки под разными именами
  дают один и тот же ключ. Чистый модуль не считает хэши сам — функцию передаёт вызывающий код.

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/unit/test_speaking_bank.py` (импорт дополнить `VariantSource, normalize, select_sources`):

```python
def announcement_text(banner: str, first_question: str) -> str:
    return (
        f"Ознакомьтесь с объявлением. {banner} Вы увидели объявление о клубе и решили получить "
        "дополнительную информацию. У Вас есть 1,5 минуты на подготовку. Затем Вам нужно задать 5 вопросов, "
        f"чтобы получить следующую информацию: 1) {first_question}; 2) часы работы; 3) стоимость; "
        "4) расписание; 5) тренеры."
    )


def project_text(theme: str) -> str:
    return (
        f"Вы выполняете вместе с другом проектную работу на тему «{theme}». Оставьте ему голосовое сообщение. "
        "Через 3 минуты будьте готовы: · объяснить выбор иллюстраций; · указать достоинства (1–2); "
        "· указать недостатки (1–2); · выразить Ваше мнение по теме проектной работы."
    )


class SelectSourcesTest(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            Block(30, ("a1.jpg",), announcement_text("欢迎加入足球俱乐部！", "адрес клуба")),
            Block(30, ("a2.jpg",), announcement_text("欢迎加入足球俱乐部！", "адрес клуба")),
            Block(30, ("a3.jpg",), announcement_text("新绘画班招生！", "местоположение")),
            Block(31, ("b1.jpg", "b2.jpg", "b3.jpg"), "Вы показываете семейный альбом."),
            Block(31, ("b1-копия.jpg", "b2.jpg", "b3.jpg"), "Вы показываете семейный альбом."),
            Block(31, ("b4.jpg", "b5.jpg", "b6.jpg"), "Вы показываете семейный альбом."),
            Block(32, ("c1.jpg", "c2.jpg"), project_text("Досуг")),
            Block(32, ("c3.jpg", "c4.jpg"), project_text("Досуг")),
            Block(32, ("c5.jpg", "c6.jpg"), project_text("Погода")),
        ]
        # «b1-копия.jpg» — тот же снимок, что и «b1.jpg», под другим именем
        self.photo_key = lambda image: image.replace("-копия", "")

    def test_builds_complete_variants_from_unique_blocks(self):
        sources = select_sources(self.blocks, photo_key=self.photo_key)

        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0].announcement.images, ("a1.jpg",))
        self.assertEqual(sources[0].album.images, ("b1.jpg", "b2.jpg", "b3.jpg"))
        self.assertEqual(sources[0].project.images, ("c1.jpg", "c2.jpg"))
        self.assertEqual(sources[1].announcement.images, ("a3.jpg",))

    def test_skips_album_whose_photo_set_repeats_under_other_names(self):
        sources = select_sources(self.blocks, photo_key=self.photo_key)

        self.assertEqual(sources[1].album.images, ("b4.jpg", "b5.jpg", "b6.jpg"))

    def test_respects_keys_already_used_by_the_project(self):
        sources = select_sources(
            self.blocks,
            photo_key=self.photo_key,
            used_banners=frozenset({normalize("欢迎加入足球俱乐部！")}),
            used_themes=frozenset({normalize("Досуг")}),
        )

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].announcement.images, ("a3.jpg",))
        self.assertEqual(sources[0].project.images, ("c5.jpg", "c6.jpg"))

    def test_does_not_put_the_same_photo_twice_into_one_variant(self):
        blocks = [
            Block(30, ("shared.jpg",), announcement_text("欢迎加入足球俱乐部！", "адрес клуба")),
            Block(31, ("shared-копия.jpg", "b2.jpg", "b3.jpg"), "Вы показываете семейный альбом."),
            Block(31, ("b4.jpg", "b5.jpg", "b6.jpg"), "Вы показываете семейный альбом."),
            Block(32, ("c1.jpg", "c2.jpg"), project_text("Досуг")),
        ]

        sources = select_sources(blocks, photo_key=self.photo_key)

        self.assertEqual(sources[0].album.images, ("b4.jpg", "b5.jpg", "b6.jpg"))

    def test_normalize_ignores_case_width_punctuation_and_yo(self):
        self.assertEqual(normalize("Времена  года!"), normalize("времена года"))
        self.assertEqual(normalize("欢迎！"), normalize("欢迎!"))
        self.assertEqual(normalize("Волонтёрская деятельность"), normalize("Волонтерская деятельность"))
```

- [ ] **Шаг 2: убедиться, что тест падает**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank -v`
Ожидается: `ImportError: cannot import name 'select_sources'`

- [ ] **Шаг 3: минимальная реализация**

Дописать в `scripts/speaking_bank.py` (импорты в начале файла дополнить
`import unicodedata` и `from collections.abc import Callable, Sequence`):

```python
_PUNCTUATION = re.compile(r"[\s!。.,、;：?()«»\"'\-—–]+")


def normalize(value: str) -> str:
    """Приводит строку к ключу сравнения: NFKC, нижний регистр, без пробелов, пунктуации и различия ё/е.

    Свести ё к е обязательно: в банке тема «Волонтерская деятельность», в demo-2025 — «Волонтёрская
    деятельность». NFKC эти строки не сближает, и повтор прошёл бы в каталог.
    """
    folded = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return _PUNCTUATION.sub("", folded)


@dataclass(frozen=True)
class VariantSource:
    """Комплект блоков на один вариант: задания 30, 31 и 32."""

    announcement: Block
    album: Block
    project: Block


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
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank -v`
Ожидается: `OK`, 17 тестов.

- [ ] **Шаг 5: проверить стиль**

Команда: `.venv/bin/python -m ruff check scripts/speaking_bank.py tests/unit/test_speaking_bank.py && .venv/bin/python -m ruff format --check scripts/speaking_bank.py tests/unit/test_speaking_bank.py`
Ожидается: `All checks passed!` и `2 files already formatted`

- [ ] **Шаг 6: коммит**

```bash
git add scripts/speaking_bank.py tests/unit/test_speaking_bank.py
git commit -m "Отбирать комплекты устных заданий без повторов"
```

---

### Задача 5: перцептивный хэш и канонизация фотографий

**Файлы:**
- Создать: `scripts/import_speaking_bank.py`
- Тест: `tests/unit/test_speaking_bank_import.py`

**Интерфейсы:**
- Использует: ничего из `speaking_bank.py`.
- Отдаёт: `HASH_SIZE = 8`, `MATCH_THRESHOLD = 4`, `fingerprint(path: Path, size: int = HASH_SIZE) -> int`,
  `canonical_index(paths: Sequence[Path], threshold: int = MATCH_THRESHOLD) -> dict[Path, Path]`.
  `canonical_index` отображает каждый путь на путь-представителя своей группы одинаковых снимков.

- [ ] **Шаг 1: написать падающий тест**

`tests/unit/test_speaking_bank_import.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.import_speaking_bank import canonical_index, fingerprint


def write_gradient(path: Path, *, shift: int = 0) -> Path:
    image = Image.new("RGB", (64, 48))
    image.putdata([((x * 4 + shift) % 256, (y * 5) % 256, 128) for y in range(48) for x in range(64)])
    image.save(path)
    return path


def write_blocks(path: Path) -> Path:
    image = Image.new("RGB", (64, 48))
    image.putdata([(255, 255, 255) if (x // 8 + y // 8) % 2 else (0, 0, 0) for y in range(48) for x in range(64)])
    image.save(path)
    return path


class FingerprintTest(unittest.TestCase):
    def test_same_picture_in_two_formats_has_the_same_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            as_png = write_gradient(root / "a.png")
            image = Image.open(as_png)
            as_jpeg = root / "a.jpg"
            image.save(as_jpeg, quality=95)

            self.assertEqual(fingerprint(as_png), fingerprint(as_jpeg))

    def test_different_pictures_have_different_fingerprints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            self.assertNotEqual(
                fingerprint(write_gradient(root / "a.png")),
                fingerprint(write_blocks(root / "b.png")),
            )


class CanonicalIndexTest(unittest.TestCase):
    def test_groups_duplicates_under_one_representative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = write_gradient(root / "a.png")
            copy = write_gradient(root / "b.png")
            other = write_blocks(root / "c.png")

            index = canonical_index([first, copy, other])

            self.assertEqual(index[first], index[copy])
            self.assertNotEqual(index[first], index[other])

    def test_representative_is_stable_regardless_of_input_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = write_gradient(root / "a.png")
            copy = write_gradient(root / "b.png")

            self.assertEqual(
                canonical_index([first, copy])[copy],
                canonical_index([copy, first])[copy],
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Шаг 2: убедиться, что тест падает**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank_import -v`
Ожидается: `ModuleNotFoundError: No module named 'scripts.import_speaking_bank'`

- [ ] **Шаг 3: минимальная реализация**

`scripts/import_speaking_bank.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image

HASH_SIZE = 8
MATCH_THRESHOLD = 4


def fingerprint(path: Path, size: int = HASH_SIZE) -> int:
    """Считает перцептивный хэш (dhash) — устойчив к пережатию и смене формата."""
    with Image.open(path) as image:
        grayscale = image.convert("L").resize((size + 1, size), Image.LANCZOS)
        pixels = list(grayscale.get_flattened_data())
    bits = 0
    for row in range(size):
        for column in range(size):
            offset = row * (size + 1) + column
            bits = bits << 1 | int(pixels[offset] < pixels[offset + 1])
    return bits


def canonical_index(paths: Sequence[Path], threshold: int = MATCH_THRESHOLD) -> dict[Path, Path]:
    """Сводит одинаковые снимки к одному представителю; порядок входа на результат не влияет."""
    fingerprints = {path: fingerprint(path) for path in paths}
    representatives: list[Path] = []
    canonical: dict[Path, Path] = {}
    for path in sorted(fingerprints):
        match = next(
            (item for item in representatives if bin(fingerprints[path] ^ fingerprints[item]).count("1") <= threshold),
            None,
        )
        if match is None:
            representatives.append(path)
            match = path
        canonical[path] = match
    return canonical
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank_import -v`
Ожидается: `OK`, 4 теста.

- [ ] **Шаг 5: коммит**

```bash
git add scripts/import_speaking_bank.py tests/unit/test_speaking_bank_import.py
git commit -m "Сравнивать фотографии банка перцептивным хэшем"
```

---

### Задача 6: команда `plan` — манифест и контактные листы

**Файлы:**
- Изменить: `scripts/import_speaking_bank.py`
- Тест: `tests/unit/test_speaking_bank_import.py`

**Интерфейсы:**
- Использует: `canonical_index`, `fingerprint` из задачи 5; `Block`, `VariantSource`, `normalize`,
  `parse_announcement`, `parse_blocks`, `parse_project`, `select_sources` из задач 1–4.
- Отдаёт: `BANK_FILE = "фипи_основной.md"`, `used_keys(content_root: Path) -> dict[str, frozenset[str]]`,
  `next_variant_number(content_root: Path) -> int`, `build_manifest(bank: Path, content_root: Path) -> dict`,
  `contact_sheets(bank: Path, images: Sequence[str], target: Path) -> list[Path]`.

  Манифест: `{"variants": [{"id": "bank-01", "number": 1, "announcement": {...}, "album": {...},
  "project": {...}}], "captions": ["media/photos/...", ...]}`, где у каждого задания есть `images`
  (список относительных путей банка) и разобранный текст; `captions` — фотографии, которым нужны
  подписи (одна от задания 30 и две от задания 32 на каждый вариант).

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/unit/test_speaking_bank_import.py` (импорт дополнить
`build_manifest, contact_sheets, next_variant_number, used_keys` и `import json`):

```python
BANK_MARKDOWN = """# Блок: задание 30
теги: Банк ФИПИ
## Стимул
1. media/photos/a1.png

## Задание
Ознакомьтесь с объявлением. 欢迎加入足球俱乐部！ Вы увидели объявление о клубе и решили получить дополнительную информацию. У Вас есть 1,5 минуты на подготовку. Затем Вам нужно задать 5 вопросов, чтобы получить следующую информацию: 1) адрес клуба; 2) часы работы; 3) стоимость; 4) расписание; 5) тренеры.

# Блок: задание 31
теги: Банк ФИПИ
## Стимул
1. media/photos/b1.png
2. media/photos/b2.png
3. media/photos/b3.png

## Задание
Вы показываете семейный альбом своему другу.

# Блок: задание 32
теги: Банк ФИПИ
## Стимул
1. media/photos/c1.png
2. media/photos/c2.png

## Задание
Вы выполняете вместе с другом проектную работу на тему «Досуг». Оставьте ему голосовое сообщение. Через 3 минуты будьте готовы: · объяснить выбор иллюстраций; · указать достоинства (1–2); · указать недостатки (1–2); · выразить Ваше мнение по теме проектной работы.
"""


def make_bank(root: Path) -> Path:
    bank = root / "bank"
    (bank / "media/photos").mkdir(parents=True)
    (bank / "фипи_основной.md").write_text(BANK_MARKDOWN, encoding="utf-8")
    for index, name in enumerate(["a1", "b1", "b2", "b3", "c1", "c2"]):
        write_gradient(bank / f"media/photos/{name}.png", shift=index * 31)
    return bank


def make_content(root: Path, variants: list[dict]) -> Path:
    content = root / "content/variants"
    content.mkdir(parents=True)
    index = []
    for variant in variants:
        (content / f"{variant['id']}.json").write_text(json.dumps(variant, ensure_ascii=False), encoding="utf-8")
        index.append(
            {
                "id": variant["id"],
                "year": variant["year"],
                "label": variant["label"],
                "file": f"content/variants/{variant['id']}.json",
            }
        )
    (content / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return root


BANK_QUESTIONS = ["адрес клуба", "часы работы", "стоимость", "расписание", "тренеры"]


def variant_stub(identifier: str, banner: str, theme: str, questions: list[str] | None = None) -> dict:
    """Опубликованный вариант каталога. По умолчанию вопросы свои — чтобы не перекрывать блок банка."""
    return {
        "id": identifier,
        "year": 2026,
        "label": identifier,
        "source": "ФИПИ",
        "totalMinutes": 14,
        "tasks": {
            "1": {
                "banner": banner,
                "questions": questions or [f"{identifier} вопрос {number}" for number in range(1, 6)],
            },
            "3": {"title": f"Проект «{theme}»"},
        },
    }


class ManifestTest(unittest.TestCase):
    def test_collects_one_variant_from_a_minimal_bank(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = make_bank(root)
            make_content(root, [])

            manifest = build_manifest(bank, root)

            self.assertEqual(len(manifest["variants"]), 1)
            variant = manifest["variants"][0]
            self.assertEqual(variant["id"], "bank-01")
            self.assertEqual(variant["announcement"]["banner"], "欢迎加入足球俱乐部！")
            self.assertEqual(variant["project"]["theme"], "Досуг")
            self.assertEqual(variant["album"]["images"], ["media/photos/b1.png", "media/photos/b2.png", "media/photos/b3.png"])

    def test_captions_list_covers_announcement_and_project_photos_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = make_bank(root)
            make_content(root, [])

            manifest = build_manifest(bank, root)

            self.assertEqual(
                manifest["captions"],
                ["media/photos/a1.png", "media/photos/c1.png", "media/photos/c2.png"],
            )

    def test_skips_blocks_already_present_in_the_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = make_bank(root)
            make_content(root, [variant_stub("demo-2026", "欢迎加入足球俱乐部！", "Досуг")])

            manifest = build_manifest(bank, root)

            self.assertEqual(manifest["variants"], [])

    def test_skips_block_whose_questions_repeat_under_another_banner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = make_bank(root)
            make_content(root, [variant_stub("demo-2026", "别的广告！", "Погода", questions=BANK_QUESTIONS)])

            manifest = build_manifest(bank, root)

            self.assertEqual(manifest["variants"], [])

    def test_numbering_continues_after_existing_bank_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = make_bank(root)
            make_content(root, [variant_stub("bank-07", "欢迎参加比赛！", "Погода")])

            self.assertEqual(next_variant_number(root), 8)
            self.assertEqual(build_manifest(bank, root)["variants"][0]["id"], "bank-08")

    def test_used_keys_reads_banners_questions_and_themes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_content(root, [variant_stub("demo-2026", "欢迎加入足球俱乐部！", "Досуг")])

            keys = used_keys(root)

            self.assertIn(normalize("欢迎加入足球俱乐部！"), keys["used_banners"])
            self.assertIn(normalize("Досуг"), keys["used_themes"])


class ContactSheetTest(unittest.TestCase):
    def test_writes_one_sheet_per_twelve_photos(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = make_bank(root)
            images = ["media/photos/a1.png"] * 13
            target = root / "sheets"

            sheets = contact_sheets(bank, images, target)

            self.assertEqual(len(sheets), 2)
            self.assertTrue(all(sheet.is_file() for sheet in sheets))
```

Импорт `normalize` в этом файле берётся из `scripts.speaking_bank`.

- [ ] **Шаг 2: убедиться, что тест падает**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank_import -v`
Ожидается: `ImportError: cannot import name 'build_manifest'`

- [ ] **Шаг 3: минимальная реализация**

Дописать в `scripts/import_speaking_bank.py` (импорты в начале дополнить `import json`, `import re`,
`from PIL import Image, ImageDraw` и блоком из `scripts.speaking_bank`):

```python
from scripts.speaking_bank import (
    VariantSource,
    normalize,
    parse_announcement,
    parse_blocks,
    parse_project,
    select_sources,
)

BANK_FILE = "фипи_основной.md"
SHEET_COLUMNS = 4
SHEET_ROWS = 3
SHEET_CELL = (320, 260)
_BANK_ID = re.compile(r"^bank-(\d+)$")


def _catalog_documents(content_root: Path) -> list[dict]:
    index_path = content_root / "content/variants/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return [json.loads((content_root / entry["file"]).read_text(encoding="utf-8")) for entry in index]


def used_keys(content_root: Path) -> dict[str, frozenset[str]]:
    """Собирает ключи повторов из уже опубликованных вариантов каталога."""
    documents = _catalog_documents(content_root)
    return {
        "used_banners": frozenset(normalize(item["tasks"]["1"]["banner"]) for item in documents),
        "used_questions": frozenset(
            normalize("|".join(item["tasks"]["1"]["questions"])) for item in documents
        ),
        "used_themes": frozenset(
            normalize(item["tasks"]["3"]["title"].replace("Проект", "").strip(" «»")) for item in documents
        ),
    }


def next_variant_number(content_root: Path) -> int:
    """Следующий свободный номер варианта банка."""
    index = json.loads((content_root / "content/variants/index.json").read_text(encoding="utf-8"))
    numbers = [int(match.group(1)) for entry in index if (match := _BANK_ID.match(entry["id"]))]
    return max(numbers, default=0) + 1


def _manifest_entry(number: int, source: VariantSource) -> dict:
    announcement = parse_announcement(source.announcement.text)
    project = parse_project(source.project.text)
    return {
        "id": f"bank-{number:02d}",
        "number": number,
        "announcement": {
            "images": list(source.announcement.images),
            "situation": announcement.situation,
            "banner": announcement.banner,
            "questions": list(announcement.questions),
        },
        "album": {"images": list(source.album.images)},
        "project": {
            "images": list(source.project.images),
            "theme": project.theme,
            "lead": project.lead,
            "prompts": list(project.prompts),
        },
    }


def build_manifest(bank: Path, content_root: Path) -> dict:
    """Отбирает комплекты и описывает их в манифесте, не трогая содержимое репозитория."""
    blocks = parse_blocks((bank / BANK_FILE).read_text(encoding="utf-8"))
    photos = sorted({bank / image for block in blocks for image in block.images})
    canonical = canonical_index(photos)
    sources = select_sources(blocks, photo_key=lambda image: canonical[bank / image].name, **used_keys(content_root))
    first = next_variant_number(content_root)
    variants = [_manifest_entry(first + offset, source) for offset, source in enumerate(sources)]
    captions = [image for variant in variants for image in variant["announcement"]["images"] + variant["project"]["images"]]
    return {"variants": variants, "captions": captions}


def contact_sheets(bank: Path, images: Sequence[str], target: Path) -> list[Path]:
    """Клеит контактные листы с подписанными именами файлов — по ним пишутся подписи к фотографиям."""
    target.mkdir(parents=True, exist_ok=True)
    per_sheet = SHEET_COLUMNS * SHEET_ROWS
    sheets: list[Path] = []
    for start in range(0, len(images), per_sheet):
        chunk = images[start : start + per_sheet]
        sheet = Image.new("RGB", (SHEET_COLUMNS * SHEET_CELL[0], SHEET_ROWS * SHEET_CELL[1]), "white")
        draw = ImageDraw.Draw(sheet)
        for position, image in enumerate(chunk):
            column, row = position % SHEET_COLUMNS, position // SHEET_COLUMNS
            box = (column * SHEET_CELL[0], row * SHEET_CELL[1])
            with Image.open(bank / image) as picture:
                thumbnail = picture.convert("RGB")
                thumbnail.thumbnail((SHEET_CELL[0] - 16, SHEET_CELL[1] - 40))
                sheet.paste(thumbnail, (box[0] + 8, box[1] + 8))
            draw.text((box[0] + 8, box[1] + SHEET_CELL[1] - 24), Path(image).name, fill="black")
        path = target / f"sheet-{len(sheets) + 1:02d}.png"
        sheet.save(path)
        sheets.append(path)
    return sheets
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank_import -v`
Ожидается: `OK`, 11 тестов.

- [ ] **Шаг 5: коммит**

```bash
git add scripts/import_speaking_bank.py tests/unit/test_speaking_bank_import.py
git commit -m "Собирать манифест вариантов и контактные листы"
```

---

### Задача 7: команда `build` — webp, файлы вариантов, index.json

**Файлы:**
- Изменить: `scripts/import_speaking_bank.py`
- Тест: `tests/unit/test_speaking_bank_import.py`

**Интерфейсы:**
- Использует: манифест из задачи 6, `EXAM_SPEC` из `trainer.domain.materials`.
- Отдаёт: `variant_document(entry: dict, captions: dict[str, str]) -> dict`,
  `write_variants(bank: Path, content_root: Path, manifest: dict, captions: dict[str, str]) -> list[str]`,
  `main(argv: list[str] | None = None) -> int` с подкомандами `plan` и `build`.

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/unit/test_speaking_bank_import.py` (импорт дополнить `main, variant_document, write_variants`):

```python
class VariantDocumentTest(unittest.TestCase):
    def setUp(self):
        self.entry = {
            "id": "bank-01",
            "number": 1,
            "announcement": {
                "images": ["media/photos/a1.png"],
                "situation": "Вы увидели объявление о клубе и решили получить дополнительную информацию.",
                "banner": "欢迎加入足球俱乐部！",
                "questions": ["адрес клуба", "часы работы", "стоимость", "расписание", "тренеры"],
            },
            "album": {"images": ["media/photos/b1.png", "media/photos/b2.png", "media/photos/b3.png"]},
            "project": {
                "images": ["media/photos/c1.png", "media/photos/c2.png"],
                "theme": "Досуг",
                "lead": "Вы выполняете проект. Говорите не более 3 минут (12–15 фраз).",
                "prompts": ["объяснить выбор", "указать достоинства", "указать недостатки", "выразить мнение"],
            },
        }
        self.captions = {
            "media/photos/a1.png": "Ребята играют в футбол на школьном поле",
            "media/photos/c1.png": "Чтение дома",
            "media/photos/c2.png": "Прогулка в парке",
        }

    def test_fills_fixed_metadata(self):
        document = variant_document(self.entry, self.captions)

        self.assertEqual(document["id"], "bank-01")
        self.assertEqual(document["year"], 2026)
        self.assertEqual(document["label"], "Банк ФИПИ · вариант 01")
        self.assertEqual(document["source"], "ФИПИ · открытый банк заданий")
        self.assertEqual(document["totalMinutes"], 14)

    def test_task_one_uses_bank_text_and_written_caption(self):
        task = variant_document(self.entry, self.captions)["tasks"]["1"]

        self.assertEqual(task["prepSeconds"], 90)
        self.assertEqual(task["answerSeconds"], 20)
        self.assertEqual(task["title"], "Пять вопросов к объявлению")
        self.assertEqual(task["banner"], "欢迎加入足球俱乐部！")
        self.assertEqual(task["image"], "assets/variants/bank-01/candidate-01.webp")
        self.assertEqual(task["imageAlt"], "Ребята играют в футбол на школьном поле")

    def test_task_two_takes_canonical_wording_and_three_images(self):
        task = variant_document(self.entry, self.captions)["tasks"]["2"]

        self.assertEqual(task["starter"], "我选择第 {n} 号照片……")
        self.assertEqual(
            task["images"],
            [
                "assets/variants/bank-01/candidate-02.webp",
                "assets/variants/bank-01/candidate-03.webp",
                "assets/variants/bank-01/candidate-04.webp",
            ],
        )

    def test_task_three_keeps_thematic_wording_and_labels(self):
        task = variant_document(self.entry, self.captions)["tasks"]["3"]

        self.assertEqual(task["title"], "Проект «Досуг»")
        self.assertEqual(task["prompts"], ["объяснить выбор", "указать достоинства", "указать недостатки", "выразить мнение"])
        self.assertEqual(task["imageLabels"], ["Чтение дома", "Прогулка в парке"])
        self.assertEqual(task["images"], ["assets/variants/bank-01/candidate-05.webp", "assets/variants/bank-01/candidate-06.webp"])


class WriteVariantsTest(unittest.TestCase):
    def test_writes_json_webp_and_index_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = make_bank(root)
            make_content(root, [])
            manifest = build_manifest(bank, root)
            captions = {image: f"подпись {image}" for image in manifest["captions"]}

            written = write_variants(bank, root, manifest, captions)

            self.assertEqual(written, ["bank-01"])
            document = json.loads((root / "content/variants/bank-01.json").read_text(encoding="utf-8"))
            self.assertEqual(document["tasks"]["1"]["image"], "assets/variants/bank-01/candidate-01.webp")
            for number in range(1, 7):
                self.assertTrue((root / f"public/assets/variants/bank-01/candidate-{number:02d}.webp").is_file())
            index = json.loads((root / "content/variants/index.json").read_text(encoding="utf-8"))
            self.assertEqual(index[-1], {
                "id": "bank-01",
                "year": 2026,
                "label": "Банк ФИПИ · вариант 01",
                "file": "content/variants/bank-01.json",
            })

    def test_converted_photos_are_webp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = make_bank(root)
            make_content(root, [])
            manifest = build_manifest(bank, root)

            write_variants(bank, root, manifest, {image: "подпись" for image in manifest["captions"]})

            with Image.open(root / "public/assets/variants/bank-01/candidate-01.webp") as image:
                self.assertEqual(image.format, "WEBP")


class CommandLineTest(unittest.TestCase):
    def test_plan_then_build_writes_the_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = make_bank(root)
            make_content(root, [])
            manifest_path = root / "manifest.json"
            captions_path = root / "captions.json"

            code = main(["plan", "--bank", str(bank), "--root", str(root), "--manifest", str(manifest_path),
                         "--sheets", str(root / "sheets")])
            self.assertEqual(code, 0)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            captions_path.write_text(
                json.dumps({image: "подпись" for image in manifest["captions"]}, ensure_ascii=False),
                encoding="utf-8",
            )

            code = main(["build", "--bank", str(bank), "--root", str(root), "--manifest", str(manifest_path),
                         "--captions", str(captions_path)])

            self.assertEqual(code, 0)
            self.assertTrue((root / "content/variants/bank-01.json").is_file())
```

- [ ] **Шаг 2: убедиться, что тест падает**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank_import -v`
Ожидается: `ImportError: cannot import name 'variant_document'`

- [ ] **Шаг 3: минимальная реализация**

Дописать в `scripts/import_speaking_bank.py` (импорты дополнить `import argparse`
и `from trainer.domain.materials import EXAM_SPEC`):

```python
VARIANT_YEAR = 2026
VARIANT_SOURCE = "ФИПИ · открытый банк заданий"
TOTAL_MINUTES = 14
WEBP_QUALITY = 82


def _asset(identifier: str, number: int) -> str:
    return f"assets/variants/{identifier}/candidate-{number:02d}.webp"


def variant_document(entry: dict, captions: dict[str, str]) -> dict:
    """Строит документ варианта по схеме schemas/variant.schema.json."""
    identifier = entry["id"]
    announcement, album, project = entry["announcement"], entry["album"], entry["project"]
    return {
        "id": identifier,
        "year": VARIANT_YEAR,
        "label": f"Банк ФИПИ · вариант {entry['number']:02d}",
        "source": VARIANT_SOURCE,
        "totalMinutes": TOTAL_MINUTES,
        "tasks": {
            "1": {
                "prepSeconds": EXAM_SPEC[1]["prepSeconds"],
                "answerSeconds": EXAM_SPEC[1]["answerSeconds"],
                "title": EXAM_SPEC[1]["title"],
                "situation": announcement["situation"],
                "banner": announcement["banner"],
                "questions": list(announcement["questions"]),
                "image": _asset(identifier, 1),
                "imageAlt": captions[announcement["images"][0]],
            },
            "2": {
                "prepSeconds": EXAM_SPEC[2]["prepSeconds"],
                "answerSeconds": EXAM_SPEC[2]["answerSeconds"],
                "title": EXAM_SPEC[2]["title"],
                "lead": EXAM_SPEC[2]["lead"],
                "prompts": list(EXAM_SPEC[2]["prompts"]),
                "starter": EXAM_SPEC[2]["starter"],
                "images": [_asset(identifier, number) for number in (2, 3, 4)],
            },
            "3": {
                "prepSeconds": EXAM_SPEC[3]["prepSeconds"],
                "answerSeconds": EXAM_SPEC[3]["answerSeconds"],
                "title": f"Проект «{project['theme']}»",
                "lead": project["lead"],
                "prompts": list(project["prompts"]),
                "images": [_asset(identifier, number) for number in (5, 6)],
                "imageLabels": [captions[image] for image in project["images"]],
            },
        },
    }


def _convert(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGB").save(target, format="WEBP", quality=WEBP_QUALITY, method=6)


def write_variants(bank: Path, content_root: Path, manifest: dict, captions: dict[str, str]) -> list[str]:
    """Пишет файлы вариантов, конвертирует фотографии и дополняет index.json."""
    index_path = content_root / "content/variants/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    written: list[str] = []
    for entry in manifest["variants"]:
        identifier = entry["id"]
        images = entry["announcement"]["images"] + entry["album"]["images"] + entry["project"]["images"]
        for number, image in enumerate(images, start=1):
            _convert(bank / image, content_root / "public" / _asset(identifier, number))
        document = variant_document(entry, captions)
        path = content_root / f"content/variants/{identifier}.json"
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        index.append(
            {
                "id": identifier,
                "year": document["year"],
                "label": document["label"],
                "file": f"content/variants/{identifier}.json",
            }
        )
        written.append(identifier)
    lines = ",\n".join(
        f'  {{ "id": "{item["id"]}", "year": {item["year"]}, '
        f'"label": "{item["label"]}", "file": "{item["file"]}" }}'
        for item in index
    )
    index_path.write_text(f"[\n{lines}\n]\n", encoding="utf-8")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Импорт устных заданий из банка ЕГЭ в каталог вариантов")
    parser.add_argument("command", choices=("plan", "build"))
    parser.add_argument("--bank", required=True, type=Path, help="каталог 1_Импорт_в_программу")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--sheets", type=Path)
    parser.add_argument("--captions", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.command == "plan":
        manifest = build_manifest(arguments.bank, arguments.root)
        arguments.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        if arguments.sheets:
            sheets = contact_sheets(arguments.bank, manifest["captions"], arguments.sheets)
            print(f"Контактных листов: {len(sheets)}")
        print(f"Отобрано вариантов: {len(manifest['variants'])}")
        return 0
    if not arguments.captions:
        parser.error("для build нужен --captions")
    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    captions = json.loads(arguments.captions.read_text(encoding="utf-8"))
    missing = [image for image in manifest["captions"] if image not in captions]
    if missing:
        print(f"Нет подписей для {len(missing)} фотографий: {', '.join(missing[:5])}")
        return 1
    written = write_variants(arguments.bank, arguments.root, manifest, captions)
    print(f"Записано вариантов: {len(written)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Команда: `.venv/bin/python -m unittest tests.unit.test_speaking_bank_import -v`
Ожидается: `OK`, 18 тестов.

- [ ] **Шаг 5: проверить стиль и весь unit-слой**

Команда: `.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check . && .venv/bin/python -m unittest discover -s tests/unit`
Ожидается: `All checks passed!`, формат без замечаний, `OK` по всем unit-тестам.

- [ ] **Шаг 6: коммит**

```bash
git add scripts/import_speaking_bank.py tests/unit/test_speaking_bank_import.py
git commit -m "Записывать варианты банка в каталог"
```

---

### Задача 8: ярлык «Вариант из банка ФИПИ» в каталоге

**Файлы:**
- Изменить: `frontend/js/catalog/variant-catalog.js:3-5`
- Тест: `tests-js/unit/views.test.js:154`

**Интерфейсы:**
- Использует: ничего.
- Отдаёт: `variantKind(id)` возвращает «Вариант из банка ФИПИ» для `bank-*`, «Официальный вариант»
  для `open-*`, «Демонстрационный вариант» для остальных.

- [ ] **Шаг 1: написать падающий тест**

В `tests-js/unit/views.test.js` в тесте `variant catalog filters and escapes exam metadata` после строки
`assert.equal(variantKind("open-2026"), "Официальный вариант");` добавить:

```javascript
  assert.equal(variantKind("bank-01"), "Вариант из банка ФИПИ");
  assert.equal(variantKind("demo-2026"), "Демонстрационный вариант");
```

- [ ] **Шаг 2: убедиться, что тест падает**

Команда: `node --test tests-js/unit/views.test.js`
Ожидается: FAIL, `expected 'Демонстрационный вариант' to equal 'Вариант из банка ФИПИ'`

- [ ] **Шаг 3: минимальная реализация**

`frontend/js/catalog/variant-catalog.js`, заменить функцию целиком:

```javascript
export function variantKind(id) {
  if (id.startsWith("open-")) return "Официальный вариант";
  if (id.startsWith("bank-")) return "Вариант из банка ФИПИ";
  return "Демонстрационный вариант";
}
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Команда: `node --test tests-js/unit/views.test.js`
Ожидается: `pass` по всем тестам.

- [ ] **Шаг 5: проверить ESLint**

Команда: `npm run lint:js`
Ожидается: выход без замечаний.

- [ ] **Шаг 6: коммит**

```bash
git add frontend/js/catalog/variant-catalog.js tests-js/unit/views.test.js
git commit -m "Подписывать варианты из банка ФИПИ отдельным видом"
```

---

### Задача 9: отбор на реальном банке и контактные листы

Данные, а не код. Результат — манифест и картинки во временном каталоге; в репозиторий ничего не попадает.

**Файлы:**
- Читать: банк по пути из «Общих ограничений»
- Создавать: `<scratchpad>/manifest.json`, `<scratchpad>/sheets/sheet-NN.png`

- [ ] **Шаг 1: запустить отбор**

```bash
.venv/bin/python -m scripts.import_speaking_bank plan \
  --bank "/Users/bronik04/Yandex.Disk.localized/Китайский язык/03-Экзамены/ЕГЭ/!Банк заданий ЕГЭ/1_Импорт_в_программу" \
  --manifest "$SCRATCHPAD/manifest.json" \
  --sheets "$SCRATCHPAD/sheets"
```

Ожидается: `Отобрано вариантов: 27` и `Контактных листов: 7` (81 фотография по 12 на лист).

Эти числа получены прогоном тех же правил на текущем состоянии банка. Если банк не менялся,
другой результат означает расхождение реализации с планом.

- [ ] **Шаг 2: сверить отбор со спецификацией**

```bash
.venv/bin/python - <<'PY'
import json, collections, os
manifest = json.load(open(os.environ["SCRATCHPAD"] + "/manifest.json"))
variants = manifest["variants"]
print("вариантов:", len(variants))
print("уникальных баннеров:", len({v["announcement"]["banner"] for v in variants}))
print("уникальных тем:", len({v["project"]["theme"] for v in variants}))
photos = [p for v in variants for p in v["announcement"]["images"] + v["album"]["images"] + v["project"]["images"]]
print("фотографий:", len(photos), "| разных имён:", len(set(photos)))
inside = [v["id"] for v in variants
          if len({*v["announcement"]["images"], *v["album"]["images"], *v["project"]["images"]}) != 6]
print("вариантов с повтором фото внутри:", inside)
PY
```

Ожидается: 27 вариантов, 27 уникальных баннеров, 27 уникальных тем, 162 фотографии, пустой список
повторов внутри варианта.

Если число вариантов отличается от 27 — не подгонять код под цифру, а разобраться: сверить, какие блоки
отсеялись и по какому правилу, и решить, ошибка это разбора или банк изменился с момента написания
спецификации.

- [ ] **Шаг 3: сохранить состояние**

Коммитить нечего — манифест и листы лежат вне репозитория. Проверить это:

```bash
git status --short
```

Ожидается: пустой вывод.

---

### Задача 10: подписи к фотографиям

Данные, а не код.

**Файлы:**
- Читать: `<scratchpad>/sheets/sheet-01.png` … `sheet-07.png` (81 фотография)
- Создавать: `<scratchpad>/captions.json`

- [ ] **Шаг 1: прочитать контактные листы**

Открыть каждый лист инструментом Read. Под каждым снимком напечатано имя файла — оно и есть ключ подписи.

- [ ] **Шаг 2: написать подписи**

`<scratchpad>/captions.json` — объект «относительный путь банка → подпись»:

```json
{
  "media/photos/p1_t03_img2.jpg": "Экскурсовод ведёт группу туристов вдоль набережной",
  "media/photos/p10_t07_img1.jpg": "Осенняя прогулка",
  "media/photos/p10_t07_img2.jpg": "Зимние забавы"
}
```

Правила:
- фотография задания 30 (`announcement`) → `imageAlt`: одно предложение, что происходит на снимке,
  без точки в конце, как в существующих вариантах («Врач беседует с пациенткой»);
- две фотографии задания 32 (`project`) → `imageLabels`: короткая именная группа, называющая предмет
  сравнения по теме варианта («Отдых дома» / «Активный отдых»). Подписи внутри одного варианта должны
  быть противопоставлены и соответствовать его теме;
- подписи на русском, без китайского текста и без слова «фотография».

- [ ] **Шаг 3: проверить полноту**

```bash
.venv/bin/python - <<'PY'
import json, os
scratch = os.environ["SCRATCHPAD"]
manifest = json.load(open(f"{scratch}/manifest.json"))
captions = json.load(open(f"{scratch}/captions.json"))
missing = [image for image in manifest["captions"] if image not in captions]
empty = [key for key, value in captions.items() if not value.strip()]
print("без подписи:", missing)
print("пустых подписей:", empty)
for variant in manifest["variants"]:
    labels = [captions.get(image, "") for image in variant["project"]["images"]]
    if labels[0] == labels[1]:
        print("одинаковые подписи в", variant["id"], labels)
PY
```

Ожидается: пустые списки и ни одной строки про одинаковые подписи.

---

### Задача 11: сборка вариантов и полная проверка

**Файлы:**
- Создать: `content/variants/bank-01.json` … `bank-27.json`,
  `public/assets/variants/bank-01/` … `bank-27/` (по 6 webp)
- Изменить: `content/variants/index.json`

- [ ] **Шаг 1: собрать варианты**

```bash
.venv/bin/python -m scripts.import_speaking_bank build \
  --bank "/Users/bronik04/Yandex.Disk.localized/Китайский язык/03-Экзамены/ЕГЭ/!Банк заданий ЕГЭ/1_Импорт_в_программу" \
  --manifest "$SCRATCHPAD/manifest.json" \
  --captions "$SCRATCHPAD/captions.json"
```

Ожидается: `Записано вариантов: 27`

- [ ] **Шаг 2: проверить контент по схеме**

Команда: `.venv/bin/python -m scripts.validate_content`
Ожидается: `Content validation passed`

- [ ] **Шаг 3: убедиться, что добавилось ровно ожидаемое**

```bash
git status --short | wc -l
ls content/variants/bank-*.json | wc -l
ls public/assets/variants/bank-*/*.webp | wc -l
```

Ожидается: 28 изменённых файлов в `content/` (27 новых + `index.json`), 27 файлов вариантов,
162 файла webp. Каталоги `public/assets/variants/bank-*` в `git status` считаются целиком, поэтому
общее число строк будет больше — сверять по трём отдельным счётчикам.

- [ ] **Шаг 4: посмотреть результат в интерфейсе**

```bash
make run
```

Открыть `http://127.0.0.1:8080/variants.html`, войти под учебной учётной записью, проверить: карточки
`bank-01`…`bank-27` подписаны «Вариант из банка ФИПИ», у каждой видна обложка, открытие варианта
показывает объявление, три фотографии альбома и две фотографии проекта с подписями. Остановить сервер.

- [ ] **Шаг 5: полная проверка**

Команда: `make check`
Ожидается: pre-commit без замечаний (ruff, ESLint, check-json, validate-content, repository-hygiene)
и `OK` по unit- и integration-тестам, coverage не ниже 70.

- [ ] **Шаг 6: коммит**

```bash
git add content/variants public/assets/variants docs/superpowers
git commit -m "Добавить 27 вариантов устной части из банка ФИПИ"
```

- [ ] **Шаг 7: завершение ветки**

Использовать superpowers:finishing-a-development-branch, чтобы выбрать между merge, PR и продолжением
работы. Отправка во внешний репозиторий — только с явного разрешения владельца проекта.
