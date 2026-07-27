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
