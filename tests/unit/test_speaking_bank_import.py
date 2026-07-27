from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.import_speaking_bank import (
    build_manifest,
    canonical_index,
    contact_sheets,
    fingerprint,
    next_variant_number,
    used_keys,
)
from scripts.speaking_bank import normalize


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
            as_jpeg = root / "a.jpg"
            with Image.open(as_png) as image:
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
            self.assertEqual(
                variant["album"]["images"],
                ["media/photos/b1.png", "media/photos/b2.png", "media/photos/b3.png"],
            )

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


if __name__ == "__main__":
    unittest.main()
