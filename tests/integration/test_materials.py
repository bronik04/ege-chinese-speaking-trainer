import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from PIL import Image

import asgi
from trainer.api import dependencies, runtime
from trainer.api.controllers import recordings
from trainer.domain.materials import EXAM_SPEC, build_content
from trainer.infrastructure.database.material_repository import SQLiteMaterialRepository
from trainer.infrastructure.images import encode_material_image
from trainer.services.materials import MaterialService


def full_draft() -> dict:
    return {
        "1": {
            "situation": "",
            "banner": "",
            "questions": ["", "", "", "", ""],
            "image": "",
            "imageAlt": "",
        },
        "2": {"images": ["", "", ""]},
        "3": {"title": "", "images": ["", ""], "imageLabels": ["", ""]},
    }


class MaterialApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_editor_mode = os.environ.get("TRAINER_EDITOR_MODE")
        cls.original_editor_emails = os.environ.get("TRAINER_EDITOR_EMAILS")
        os.environ["TRAINER_EDITOR_MODE"] = "allowlist"
        os.environ["TRAINER_EDITOR_EMAILS"] = ",".join(
            (
                "author@example.test",
                "cleanup@example.test",
                "strict-content@example.test",
                "canonical-content@example.test",
            )
        )
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        database_path = root / "trainer.sqlite3"
        audio_dir = root / "audio"
        runtime.DATA_DIR = root
        runtime.DB_PATH = database_path
        runtime.AUDIO_DIR = audio_dir
        runtime.MATERIAL_ASSET_DIR = root / "material-assets"
        dependencies.DATA_DIR = root
        dependencies.AUDIO_DIR = audio_dir
        recordings.DATA_DIR = root
        recordings.AUDIO_DIR = audio_dir
        cls.client_context = TestClient(asgi.app)
        cls.client = cls.client_context.__enter__()
        cls.origin = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        for name, value in {
            "TRAINER_EDITOR_MODE": cls.original_editor_mode,
            "TRAINER_EDITOR_EMAILS": cls.original_editor_emails,
        }.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cls.temp_dir.cleanup()

    def setUp(self):
        self.client.cookies.clear()

    def register(self, email="author@example.test"):
        response = self.client.post(
            "/api/auth/register",
            headers=self.origin,
            json={"email": email, "password": "password123", "displayName": "Автор"},
        )
        self.assertEqual(response.status_code, 201, response.text)

    def verify_email(self, email="author@example.test"):
        entries = [json.loads(line) for line in (runtime.DATA_DIR / "outbox.log").read_text().splitlines()]
        message = next(entry for entry in reversed(entries) if entry["to"] == email and "?verify=" in entry["body"])
        token = parse_qs(urlparse(message["body"].strip().splitlines()[-1]).query)["verify"][0]
        response = self.client.post("/api/auth/email/confirm", headers=self.origin, json={"token": token})
        self.assertEqual(response.status_code, 200, response.text)

    def register_verified_editor(self, email="author@example.test"):
        self.register(email)
        self.verify_email(email)

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
        blocked = self.client.get("/api/materials").json()
        self.assertFalse(blocked["canCreate"])
        self.verify_email()
        official = json.loads(
            (Path(__file__).resolve().parents[2] / "content/variants/index.json").read_text(encoding="utf-8")
        )
        listing = self.client.get("/api/materials").json()
        self.assertEqual({item["id"] for item in listing["materials"]}, {item["id"] for item in official})
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
        self.assertEqual(
            self.client.put("/api/materials/author-photo-task", headers=self.origin, json=draft).status_code, 200
        )
        published = self.client.post("/api/materials/author-photo-task/publish", headers=self.origin, json={})
        self.assertEqual(published.status_code, 200, published.text)
        detail = self.client.get("/api/materials/author-photo-task").json()["material"]
        self.assertEqual(detail["kind"], "task")
        self.assertEqual(detail["tasks"]["2"]["prepSeconds"], 120)
        self.assertEqual(detail["tasks"]["2"]["prompts"], EXAM_SPEC[2]["prompts"])
        self.assertEqual(self.client.get(asset_url).status_code, 200)

        with runtime.connect() as database:
            teacher_id = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                ("snapshot-owner@example.test", "x", "Teacher", "teacher", 1),
            ).lastrowid
            group_id = database.execute(
                "INSERT INTO study_groups(teacher_id,name,join_code,created_at) VALUES (?,?,?,?)",
                (teacher_id, "Snapshots", "SNAP01", 1),
            ).lastrowid
            database.execute(
                """INSERT INTO assignments(group_id,teacher_id,title,variant_id,tasks_json,created_at,material_snapshot_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (group_id, teacher_id, "Snapshot", draft["slug"], "[2]", 1, json.dumps(detail)),
            )
        replacement = self.client.post(
            "/api/materials/author-photo-task/assets",
            headers={**self.origin, "Content-Type": "image/png"},
            content=self.image_bytes(),
        ).json()["asset"]["url"]
        draft["content"] = {"2": {"images": [replacement, replacement, replacement]}}
        self.assertEqual(
            self.client.put("/api/materials/author-photo-task", headers=self.origin, json=draft).status_code, 200
        )
        self.assertEqual(
            self.client.post("/api/materials/author-photo-task/publish", headers=self.origin, json={}).status_code,
            200,
        )
        self.assertEqual(self.client.get(asset_url).status_code, 200)

        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/materials/author-photo-task").status_code, 404)
        self.assertEqual([item["id"] for item in self.client.get("/api/materials").json()["materials"]], ["open-2026"])

    def test_full_variant_uses_fixed_exam_spec(self):
        content = build_content(
            "full",
            None,
            {
                "1": {
                    "situation": "Достаточно длинная ситуация",
                    "banner": "欢迎",
                    "questions": ["Вопрос"] * 5,
                    "image": "/api/material-assets/1",
                    "imageAlt": "Фото",
                },
                "2": {"images": ["/api/material-assets/1"] * 3},
                "3": {
                    "title": "Проект «Отдых»",
                    "images": ["/api/material-assets/1"] * 2,
                    "imageLabels": ["Первое", "Второе"],
                },
            },
        )
        self.assertEqual(
            [(content[str(n)]["prepSeconds"], content[str(n)]["answerSeconds"]) for n in (1, 2, 3)],
            [(90, 20), (120, 120), (180, 180)],
        )

    def test_material_request_rejects_invalid_content_shapes(self):
        email = "strict-content@example.test"
        self.register_verified_editor(email)
        base = {
            "slug": "strict-content",
            "kind": "task",
            "taskNumber": 2,
            "title": "Строгий черновик",
            "year": 2026,
            "source": "Автор",
            "content": {"2": {"images": ["", "", ""]}},
        }
        invalid_contents = (
            {"2": {"images": ["", ""]}},
            {"2": {"images": ["", 2, ""]}},
            {"2": {"images": ["", "", ""], "lead": "лишнее"}},
            {
                "3": {
                    "title": "",
                    "images": ["", ""],
                    "imageLabels": ["", ""],
                }
            },
        )
        for index, content in enumerate(invalid_contents):
            payload = {
                **base,
                "slug": f"strict-content-{index}",
                "content": content,
            }
            response = self.client.post("/api/materials", headers=self.origin, json=payload)
            with self.subTest(index=index):
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["code"], "request_validation_failed")

        full_with_number = {
            **base,
            "slug": "strict-full-number",
            "kind": "full",
            "taskNumber": 2,
            "content": full_draft(),
        }
        response = self.client.post("/api/materials", headers=self.origin, json=full_with_number)
        self.assertEqual(response.status_code, 422, response.text)

    def test_material_draft_is_canonical_and_legacy_content_remains_readable(self):
        email = "canonical-content@example.test"
        self.register_verified_editor(email)
        draft = {
            "slug": "canonical-content",
            "kind": "task",
            "taskNumber": 2,
            "title": "Канонический черновик",
            "year": 2026,
            "source": "Автор",
            "content": {"2": {"images": ["", "", ""]}},
        }
        response = self.client.post("/api/materials", headers=self.origin, json=draft)
        self.assertEqual(response.status_code, 201, response.text)

        with runtime.connect() as database:
            stored = database.execute(
                "SELECT content_json FROM materials WHERE slug=?",
                (draft["slug"],),
            ).fetchone()["content_json"]
            self.assertEqual(json.loads(stored), draft["content"])
            owner_id = database.execute(
                "SELECT id FROM users WHERE email=?",
                (email,),
            ).fetchone()["id"]
            legacy = json.dumps({"legacy": True}, separators=(",", ":"))
            database.execute(
                """INSERT INTO materials
                   (slug,owner_id,kind,task_number,title,year,source,status,content_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,'draft',?,?,?)""",
                (
                    "legacy-content",
                    owner_id,
                    "task",
                    2,
                    "Legacy",
                    2026,
                    "Legacy",
                    legacy,
                    1,
                    1,
                ),
            )

        incomplete = self.client.post(
            "/api/materials/canonical-content/publish",
            headers=self.origin,
            json={},
        )
        self.assertEqual(incomplete.status_code, 400, incomplete.text)
        self.assertEqual(incomplete.json()["code"], "material_incomplete")

        detail = self.client.get("/api/materials/legacy-content")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["material"]["tasks"], {"legacy": True})
        with runtime.connect() as database:
            unchanged = database.execute("SELECT content_json FROM materials WHERE slug='legacy-content'").fetchone()[
                "content_json"
            ]
        self.assertEqual(unchanged, legacy)

    def test_asset_upload_deletes_stored_object_when_metadata_insert_fails(self):
        email = "cleanup@example.test"
        self.register(email)
        self.verify_email(email)
        draft = {
            "slug": "cleanup-task",
            "kind": "task",
            "taskNumber": 2,
            "title": "Cleanup task",
            "year": 2026,
            "source": "Test source",
            "content": {"2": {"images": ["", "", ""]}},
        }
        self.assertEqual(self.client.post("/api/materials", headers=self.origin, json=draft).status_code, 201)

        class FailingStorage:
            def __init__(self):
                self.deleted = []

            def put(self, key, source, content_type):
                self.key = key

            def delete(self, key):
                self.deleted.append(key)

        storage = FailingStorage()
        original_connect = runtime.connect
        calls = 0

        def failing_connect():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise sqlite3.IntegrityError("metadata failed")
            return original_connect()

        service = MaterialService(
            SQLiteMaterialRepository(failing_connect),
            project_root=runtime.ROOT,
            asset_root=runtime.MATERIAL_ASSET_DIR,
            storage=storage,
            image_encoder=encode_material_image,
            editor_emails=os.environ["TRAINER_EDITOR_EMAILS"],
            max_image_body=min(runtime.MAX_AUDIO_BODY, 5_000_000),
        )
        with patch.object(runtime, "material_service", return_value=service):
            response = self.client.post(
                "/api/materials/cleanup-task/assets",
                headers={**self.origin, "Content-Type": "image/png"},
                content=self.image_bytes(),
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(storage.deleted, [storage.key])


if __name__ == "__main__":
    unittest.main()
