from __future__ import annotations

import argparse
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
from trainer.domain.materials import EXAM_SPEC

HASH_SIZE = 8
MATCH_THRESHOLD = 4
BANK_FILE = "фипи_основной.md"
SHEET_COLUMNS = 4
SHEET_ROWS = 3
SHEET_CELL = (320, 260)
VARIANT_YEAR = 2026
VARIANT_SOURCE = "ФИПИ · открытый банк заданий"
TOTAL_MINUTES = 14
WEBP_QUALITY = 82
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


def _asset(identifier: str, number: int) -> str:
    return f"assets/variants/{identifier}/candidate-{number:02d}.webp"


def variant_document(entry: dict, captions: dict[str, str]) -> dict:
    """Строит документ варианта по схеме schemas/variant.schema.json."""
    identifier = entry["id"]
    announcement, project = entry["announcement"], entry["project"]
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
        f'  {{ "id": "{item["id"]}", "year": {item["year"]}, "label": "{item["label"]}", "file": "{item["file"]}" }}'
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
