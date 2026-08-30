from __future__ import annotations

import io
import unittest

from PIL import Image

from trainer.infrastructure.images import encode_material_image
from trainer.services.material_repository import MaterialImageError


def png_bytes(size: tuple[int, int], mode: str = "RGB") -> bytes:
    stream = io.BytesIO()
    Image.new(mode, size, "#8b1a1a").save(stream, "PNG")
    return stream.getvalue()


class MaterialImageEncoderTest(unittest.TestCase):
    def test_returns_bounded_webp(self):
        encoded = encode_material_image(png_bytes((2400, 1800)))

        with Image.open(io.BytesIO(encoded)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (1600, 1200))

    def test_rejects_invalid_and_out_of_bounds_images(self):
        fixtures = (
            b"not-image",
            png_bytes((319, 240)),
            png_bytes((5000, 4001)),
        )

        for body in fixtures:
            with self.subTest(size=len(body)), self.assertRaises(MaterialImageError):
                encode_material_image(body)


if __name__ == "__main__":
    unittest.main()
