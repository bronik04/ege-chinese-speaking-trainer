import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import asgi
import server


class FastApiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        server.DATA_DIR = Path(cls.temp_dir.name)
        server.DB_PATH = server.DATA_DIR / "trainer.sqlite3"
        server.AUDIO_DIR = server.DATA_DIR / "audio"
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
            json={"email": "asgi@example.test", "password": "password123", "displayName": "ASGI User", "role": "student"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(response.json()["user"]["emailVerified"])


if __name__ == "__main__":
    unittest.main()
