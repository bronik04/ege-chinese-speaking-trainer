from __future__ import annotations

import unittest
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import patch

from trainer.api.controllers import materials
from trainer.api.errors import ApiError
from trainer.api.results import RequestContext
from trainer.services.materials import MaterialError


class FailingMaterialService:
    def __init__(self, error: MaterialError):
        self.error = error

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise self.error

        return fail


class MaterialControllerErrorContractTest(unittest.TestCase):
    def setUp(self):
        self.user = {
            "id": 7,
            "email": "author@example.test",
            "emailVerified": True,
        }
        self.context = RequestContext("127.0.0.1", "tests")
        self.payload = SimpleNamespace(
            slug="author-task",
            kind="task",
            taskNumber=2,
            title="Авторский материал",
            year=2026,
            source="Автор",
            content={"2": {}},
        )

    def test_semantic_errors_keep_the_public_api_contract(self):
        cases = (
            (
                MaterialError("invalid_metadata", "Проверьте название"),
                lambda: materials.material_create(self.payload, self.user, self.context),
                HTTPStatus.BAD_REQUEST,
                "invalid_material",
                "Проверьте название",
            ),
            (
                MaterialError("slug_exists"),
                lambda: materials.material_create(self.payload, self.user, self.context),
                HTTPStatus.CONFLICT,
                "material_slug_exists",
                "Материал с таким идентификатором уже существует",
            ),
            (
                MaterialError("not_found"),
                lambda: materials.material_get("missing", self.user),
                HTTPStatus.NOT_FOUND,
                "material_not_found",
                "Материал не найден",
            ),
            (
                MaterialError("incomplete", "Необходимо добавить изображений: 3"),
                lambda: materials.material_publish("author-task", self.user, self.context),
                HTTPStatus.BAD_REQUEST,
                "material_incomplete",
                "Необходимо добавить изображений: 3",
            ),
            (
                MaterialError("foreign_asset"),
                lambda: materials.material_publish("author-task", self.user, self.context),
                HTTPStatus.BAD_REQUEST,
                "invalid_material_asset",
                "Одно из изображений не принадлежит материалу",
            ),
            (
                MaterialError("unsupported_image"),
                lambda: materials.material_asset_create("author-task", b"image", "image/gif", self.user, self.context),
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "unsupported_image",
                "Поддерживаются JPG, PNG и WebP",
            ),
            (
                MaterialError("image_too_large"),
                lambda: materials.material_asset_create("author-task", b"image", "image/png", self.user, self.context),
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "image_too_large",
                "Изображение превышает 5 МБ",
            ),
            (
                MaterialError("invalid_image"),
                lambda: materials.material_asset_create("author-task", b"image", "image/png", self.user, self.context),
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_image",
                "Некорректное изображение",
            ),
            (
                MaterialError("asset_not_found"),
                lambda: materials.material_asset_get(999, self.user),
                HTTPStatus.NOT_FOUND,
                "asset_not_found",
                "Изображение не найдено",
            ),
        )

        for error, action, status, code, message in cases:
            with (
                self.subTest(reason=error.reason),
                patch.object(
                    materials.runtime,
                    "material_service",
                    return_value=FailingMaterialService(error),
                ),
                self.assertRaises(ApiError) as caught,
            ):
                action()

            self.assertEqual(caught.exception.status, status)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.message, message)


if __name__ == "__main__":
    unittest.main()
