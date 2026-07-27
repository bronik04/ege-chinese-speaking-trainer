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


if __name__ == "__main__":
    unittest.main()
