from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from trainer.main import app


class RequestGuardTest(unittest.TestCase):
    def test_cross_origin_post_is_rejected_before_the_route(self):
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "x"},
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "invalid_origin")


if __name__ == "__main__":
    unittest.main()
