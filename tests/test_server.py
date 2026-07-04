import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server


class SecurityHelpersTest(unittest.TestCase):
    def setUp(self):
        with server._AUTH_ATTEMPTS_LOCK:
            server._AUTH_ATTEMPTS.clear()

    def test_password_hash_round_trip(self):
        encoded = server.password_hash("correct horse battery staple")
        self.assertTrue(server.password_matches("correct horse battery staple", encoded))
        self.assertFalse(server.password_matches("wrong password", encoded))

    def test_same_origin_requires_browser_source(self):
        host = "127.0.0.1:8080"
        self.assertTrue(server.request_has_same_origin(host, "http://127.0.0.1:8080", None, "same-origin"))
        self.assertTrue(server.request_has_same_origin(host, None, "http://127.0.0.1:8080/page", "same-origin"))
        self.assertFalse(server.request_has_same_origin(host, None, None, None))
        self.assertFalse(server.request_has_same_origin(host, "https://evil.example", None, "cross-site"))

    def test_login_rate_limit(self):
        for offset in range(8):
            self.assertEqual(server.auth_rate_limit("login", "127.0.0.1", "user@example.test", 1000 + offset), 0)
        self.assertGreater(server.auth_rate_limit("login", "127.0.0.1", "user@example.test", 1008), 0)
        self.assertEqual(server.auth_rate_limit("login", "127.0.0.1", "other@example.test", 1008), 0)


class ApiFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        server.DATA_DIR = Path(cls.temp_dir.name)
        server.DB_PATH = server.DATA_DIR / "trainer.sqlite3"
        server.init_database()
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.TrainerHandler)
        cls.httpd.daemon_threads = True
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.port = cls.httpd.server_address
        cls.origin = f"http://{cls.host}:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.temp_dir.cleanup()

    def request(self, method, path, payload=None, cookie=None, include_origin=True):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=3)
        headers = {}
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        if include_origin:
            headers["Origin"] = self.origin
            headers["Sec-Fetch-Site"] = "same-origin"
        if cookie:
            headers["Cookie"] = cookie
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read() or b"{}")
        response_headers = dict(response.getheaders())
        connection.close()
        return response.status, data, response_headers

    @staticmethod
    def cookie_from(headers):
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_teacher_student_progress_flow(self):
        teacher = {
            "email": "teacher@example.test", "password": "teacher123",
            "displayName": "Ли Лаоши", "role": "teacher",
        }
        status, _, headers = self.request("POST", "/api/auth/register", teacher)
        self.assertEqual(status, 201)
        teacher_cookie = self.cookie_from(headers)

        student = {
            "email": "student@example.test", "password": "student123",
            "displayName": "Анна Петрова", "role": "student",
        }
        status, _, headers = self.request("POST", "/api/auth/register", student)
        self.assertEqual(status, 201)
        student_cookie = self.cookie_from(headers)

        status, group_payload, _ = self.request(
            "POST", "/api/teacher/groups", {"name": "11 класс"}, teacher_cookie
        )
        self.assertEqual(status, 201)
        code = group_payload["group"]["code"]

        status, _, _ = self.request("POST", "/api/groups/join", {"code": code}, student_cookie)
        self.assertEqual(status, 200)
        progress = {
            "version": 1, "updatedAt": "2026-07-04T12:00:00.000Z", "settings": {},
            "activeRun": None,
            "runs": [{"id": "run-1", "status": "completed", "completedTasks": [1, 2]}],
        }
        status, _, _ = self.request("PUT", "/api/progress", {"progress": progress}, student_cookie)
        self.assertEqual(status, 200)

        status, dashboard, _ = self.request("GET", "/api/teacher/dashboard", cookie=teacher_cookie)
        self.assertEqual(status, 200)
        visible_student = dashboard["groups"][0]["students"][0]
        self.assertEqual(visible_student["name"], "Анна Петрова")
        self.assertEqual(visible_student["completedRuns"], 1)
        self.assertEqual(visible_student["completedTasks"], 2)

    def test_mutation_without_origin_is_rejected(self):
        status, payload, _ = self.request(
            "POST", "/api/auth/login", {"email": "nobody@example.test", "password": "password123"},
            include_origin=False,
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "Invalid request origin")

    def test_login_endpoint_returns_rate_limit(self):
        payload = {"email": "rate-limit@example.test", "password": "password123"}
        for _ in range(8):
            status, _, _ = self.request("POST", "/api/auth/login", payload)
            self.assertEqual(status, 401)
        status, body, headers = self.request("POST", "/api/auth/login", payload)
        self.assertEqual(status, 429)
        self.assertIn("Retry-After", headers)
        self.assertGreater(body["retryAfter"], 0)


if __name__ == "__main__":
    unittest.main()
