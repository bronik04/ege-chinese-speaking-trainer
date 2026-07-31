from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trainer.api.errors import ApiError, api_error_handler


class ErrorContractTest(unittest.TestCase):
    def client(self) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(ApiError, api_error_handler)

        @app.get("/boom")
        async def boom():
            raise ApiError("teacher_not_allowed", "Роль преподавателя недоступна", 403)

        return TestClient(app, raise_server_exceptions=False)

    def test_handler_keeps_error_payload_shape(self):
        response = self.client().get("/boom")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "teacher_not_allowed")
        self.assertEqual(response.json()["message"], "Роль преподавателя недоступна")


if __name__ == "__main__":
    unittest.main()
