import io
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

import asgi
import server
from api import runtime
from api.controllers import common, materials, recordings
from backend.materials import EXAM_SPEC, build_content


class MaterialApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        server.DATA_DIR = root
        server.DB_PATH = root / "trainer.sqlite3"
        server.AUDIO_DIR = root / "audio"
        runtime.DATA_DIR = root
        runtime.DB_PATH = server.DB_PATH
        runtime.AUDIO_DIR = server.AUDIO_DIR
        runtime.MATERIAL_ASSET_DIR = root / "material-assets"
        common.DATA_DIR = root
        common.AUDIO_DIR = server.AUDIO_DIR
        materials.MATERIAL_ASSET_DIR = runtime.MATERIAL_ASSET_DIR
        recordings.DATA_DIR = root
        recordings.AUDIO_DIR = server.AUDIO_DIR
        cls.client_context = TestClient(asgi.app)
        cls.client = cls.client_context.__enter__()
        cls.origin = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def setUp(self):
        self.client.cookies.clear()

    def register(self, email="author@example.test"):
        response = self.client.post(
            "/api/auth/register",
            headers=self.origin,
            json={"email": email, "password": "password123", "displayName": "Автор", "role": "student"},
        )
        self.assertEqual(response.status_code, 201, response.text)

    @staticmethod
    def image_bytes():
        stream = io.BytesIO()
        Image.new("RGB", (640, 480), "#8b1a1a").save(stream, "PNG")
        return stream.getvalue()

    def test_guest_can_only_access_open_2026(self):
        listing = self.client.get("/api/materials")
        self.assertEqual([item["id"] for item in listing.json()["materials"]], ["open-2026"])
        self.assertFalse(listing.json()["canCreate"])
        self.assertEqual(self.client.get("/api/materials/open-2026").status_code, 200)
        self.assertEqual(self.client.get("/api/materials/demo-2026").status_code, 404)
        self.assertEqual(self.client.get("/data/variants/demo-2026.json").status_code, 404)

    def test_user_creates_uploads_and_publishes_standalone_task(self):
        self.register()
        listing = self.client.get("/api/materials").json()
        self.assertEqual(len(listing["materials"]), 7)
        self.assertTrue(listing["canCreate"])
        draft = {
            "slug": "author-photo-task",
            "kind": "task",
            "taskNumber": 2,
            "title": "Авторское описание фото",
            "year": 2026,
            "source": "Авторский материал",
            "content": {"2": {"images": ["", "", ""]}},
        }
        created = self.client.post("/api/materials", headers=self.origin, json=draft)
        self.assertEqual(created.status_code, 201, created.text)
        upload = self.client.post(
            "/api/materials/author-photo-task/assets",
            headers={**self.origin, "Content-Type": "image/png"},
            content=self.image_bytes(),
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        asset_url = upload.json()["asset"]["url"]
        draft["content"] = {"2": {"images": [asset_url, asset_url, asset_url]}}
        self.assertEqual(self.client.put("/api/materials/author-photo-task", headers=self.origin, json=draft).status_code, 200)
        published = self.client.post("/api/materials/author-photo-task/publish", headers=self.origin, json={})
        self.assertEqual(published.status_code, 200, published.text)
        detail = self.client.get("/api/materials/author-photo-task").json()["material"]
        self.assertEqual(detail["kind"], "task")
        self.assertEqual(detail["tasks"]["2"]["prepSeconds"], 120)
        self.assertEqual(detail["tasks"]["2"]["prompts"], EXAM_SPEC[2]["prompts"])
        self.assertEqual(self.client.get(asset_url).status_code, 200)

        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/materials/author-photo-task").status_code, 404)
        self.assertEqual([item["id"] for item in self.client.get("/api/materials").json()["materials"]], ["open-2026"])

    def test_full_variant_uses_fixed_exam_spec(self):
        content = build_content(
            "full",
            None,
            {
                "1": {"situation": "Достаточно длинная ситуация", "banner": "欢迎", "questions": ["Вопрос"] * 5, "image": "/api/material-assets/1", "imageAlt": "Фото"},
                "2": {"images": ["/api/material-assets/1"] * 3},
                "3": {"title": "Проект «Отдых»", "images": ["/api/material-assets/1"] * 2, "imageLabels": ["Первое", "Второе"]},
            },
        )
        self.assertEqual([(content[str(n)]["prepSeconds"], content[str(n)]["answerSeconds"]) for n in (1, 2, 3)], [(90, 20), (120, 120), (180, 180)])


if __name__ == "__main__":
    unittest.main()
