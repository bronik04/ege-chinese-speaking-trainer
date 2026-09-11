from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

from trainer.services.material_repository import MaterialImageError


def encode_material_image(body: bytes) -> bytes:
    try:
        image = Image.open(io.BytesIO(body))
        image.load()
        if image.width < 320 or image.height < 240 or image.width * image.height > 20_000_000:
            raise MaterialImageError
        image.thumbnail((1600, 1600))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        encoded = io.BytesIO()
        image.save(encoded, "WEBP", quality=84, method=6)
        return encoded.getvalue()
    except MaterialImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise MaterialImageError from error
