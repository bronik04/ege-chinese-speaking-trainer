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
        health = self.client.get("/api/health").json()
        self.assertTrue(health["ok"])
        self.assertEqual(health["database"], "sqlite")
        self.assertEqual(set(health["errors"]), {"responses4xx", "responses5xx", "lastFailureAt"})
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/variants.html").status_code, 200)
        self.assertEqual(self.client.get("/variants.css").status_code, 200)
        self.assertEqual(self.client.get("/variant-editor.html").status_code, 200)
        self.assertEqual(self.client.get("/variant-editor.css").status_code, 200)
        self.assertEqual(self.client.get("/data/variants/index.json").status_code, 404)
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
        self.assertEqual(payload["code"], "request_validation_failed")
        self.assertEqual(payload["message"], "Некорректные данные запроса")
        self.assertEqual({item["location"] for item in payload["fields"]}, {"displayName", "unexpected"})

    def test_error_response_and_header_share_request_id(self):
        response = self.client.post(
            "/api/auth/login",
            headers={
                "Origin": "http://testserver",
                "Sec-Fetch-Site": "same-origin",
                "X-Request-ID": "e2e-request-123",
            },
            json={"email": "missing@example.test", "password": "password123"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["X-Request-ID"], "e2e-request-123")
        self.assertEqual(
            response.json(),
            {
                "code": "invalid_credentials",
                "message": "Неверный email или пароль",
                "requestId": "e2e-request-123",
            },
        )

    def test_openapi_exposes_request_schemas(self):
        document = self.client.get("/openapi.json").json()
        operation = document["paths"]["/api/teacher/assignments"]["post"]
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["$ref"], "#/components/schemas/AssignmentRequest")

    def test_framework_http_errors_use_api_error_contract(self):
        response = self.client.put("/api/auth/me", headers={"X-Request-ID": "method-request-123"})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["code"], "method_not_allowed")
        self.assertEqual(response.json()["requestId"], "method-request-123")


if __name__ == "__main__":
    unittest.main()
