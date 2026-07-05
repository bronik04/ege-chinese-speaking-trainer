import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import asgi
import server
from api import runtime
from api.controllers import common, recordings


class FastApiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        server.DATA_DIR = Path(cls.temp_dir.name)
        server.DB_PATH = server.DATA_DIR / "trainer.sqlite3"
        server.AUDIO_DIR = server.DATA_DIR / "audio"
        runtime.DATA_DIR = server.DATA_DIR
        runtime.DB_PATH = server.DB_PATH
        runtime.AUDIO_DIR = server.AUDIO_DIR
        common.DATA_DIR = server.DATA_DIR
        common.AUDIO_DIR = server.AUDIO_DIR
        recordings.DATA_DIR = server.DATA_DIR
        recordings.AUDIO_DIR = server.AUDIO_DIR
        cls.client_context = TestClient(asgi.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def test_health_static_and_private_data_boundary(self):
        self.assertEqual(self.client.get("/api/health").json(), {"ok": True, "database": "sqlite"})
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/var/trainer.sqlite3").status_code, 404)

    def test_mutation_uses_existing_api_contract(self):
        response = self.client.post(
            "/api/auth/register",
            headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
            json={
                "email": "asgi@example.test",
                "password": "password123",
                "displayName": "ASGI User",
                "role": "student",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(response.json()["user"]["emailVerified"])

    def test_pydantic_rejects_incomplete_and_extra_fields(self):
        response = self.client.post(
            "/api/auth/register",
            headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
            json={
                "email": "invalid@example.test",
                "password": "password123",
                "role": "student",
                "unexpected": True,
            },
        )
        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertEqual(payload["error"], "Некорректные данные запроса")
        self.assertEqual({item["location"] for item in payload["fields"]}, {"displayName", "unexpected"})

    def test_openapi_exposes_request_schemas(self):
        document = self.client.get("/openapi.json").json()
        operation = document["paths"]["/api/teacher/assignments"]["post"]
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["$ref"], "#/components/schemas/AssignmentRequest")


if __name__ == "__main__":
    unittest.main()
