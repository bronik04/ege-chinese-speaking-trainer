from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.speaking_bank import (
    VariantSource,
    normalize,
    parse_announcement,
    parse_blocks,
    parse_project,
    select_sources,
)

HASH_SIZE = 8
MATCH_THRESHOLD = 4
BANK_FILE = "фипи_основной.md"
SHEET_COLUMNS = 4
SHEET_ROWS = 3
SHEET_CELL = (320, 260)
_BANK_ID = re.compile(r"^bank-(\d+)$")


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


def _catalog_documents(content_root: Path) -> list[dict]:
    index_path = content_root / "content/variants/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return [json.loads((content_root / entry["file"]).read_text(encoding="utf-8")) for entry in index]


def used_keys(content_root: Path) -> dict[str, frozenset[str]]:
    """Собирает ключи повторов из уже опубликованных вариантов каталога."""
    documents = _catalog_documents(content_root)
    return {
        "used_banners": frozenset(normalize(item["tasks"]["1"]["banner"]) for item in documents),
        "used_questions": frozenset(normalize("|".join(item["tasks"]["1"]["questions"])) for item in documents),
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
    captions = [
        image for variant in variants for image in variant["announcement"]["images"] + variant["project"]["images"]
    ]
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
