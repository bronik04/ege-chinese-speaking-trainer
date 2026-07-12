import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import asgi
from trainer.api import dependencies, runtime
from trainer.api.controllers import recordings
from trainer.api.security import request_has_same_origin
from trainer.domain.accounts import password_hash, password_matches


class SecurityHelpersTest(unittest.TestCase):
    def test_password_hash_round_trip(self):
        encoded = password_hash("correct horse battery staple")
        self.assertTrue(password_matches("correct horse battery staple", encoded))
        self.assertFalse(password_matches("wrong password", encoded))

    def test_same_origin_requires_browser_source(self):
        host = "127.0.0.1:8080"
        self.assertTrue(request_has_same_origin(host, "http://127.0.0.1:8080", None, "same-origin"))
        self.assertTrue(request_has_same_origin(host, None, "http://127.0.0.1:8080/page", "same-origin"))
        self.assertFalse(request_has_same_origin(host, None, None, None))
        self.assertFalse(request_has_same_origin(host, "https://evil.example", None, "cross-site"))


class ApiFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_teacher_emails = os.environ.get("TRAINER_TEACHER_EMAILS")
        os.environ["TRAINER_TEACHER_EMAILS"] = "teacher@example.test"
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        runtime.DATA_DIR = root
        runtime.DB_PATH = root / "trainer.sqlite3"
        runtime.AUDIO_DIR = root / "audio"
        dependencies.DATA_DIR = root
        dependencies.AUDIO_DIR = runtime.AUDIO_DIR
        recordings.DATA_DIR = root
        recordings.AUDIO_DIR = runtime.AUDIO_DIR
        cls.original_validate_duration = recordings.validate_duration
        recordings.validate_duration = lambda path, task: 1.0
        cls.client_context = TestClient(asgi.app)
        cls.client = cls.client_context.__enter__()
        cls.origin = "http://testserver"

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        recordings.validate_duration = cls.original_validate_duration
        if cls.original_teacher_emails is None:
            os.environ.pop("TRAINER_TEACHER_EMAILS", None)
        else:
            os.environ["TRAINER_TEACHER_EMAILS"] = cls.original_teacher_emails
        cls.temp_dir.cleanup()

    def request(self, method, path, payload=None, cookie=None, include_origin=True):
        headers = {}
        if include_origin:
            headers["Origin"] = self.origin
            headers["Sec-Fetch-Site"] = "same-origin"
        if cookie:
            headers["Cookie"] = cookie
        self.client.cookies.clear()
        response = self.client.request(method, path, json=payload, headers=headers)
        return response.status_code, response.json() if response.content else {}, dict(response.headers)

    def request_audio(self, path, data, cookie):
        self.client.cookies.clear()
        response = self.client.post(
            path,
            content=data,
            headers={
                "Content-Type": "audio/webm",
                "Origin": self.origin,
                "Sec-Fetch-Site": "same-origin",
                "Cookie": cookie,
            },
        )
        return response.status_code, response.json()

    def request_bytes(self, path, cookie):
        self.client.cookies.clear()
        response = self.client.get(path, headers={"Cookie": cookie})
        return response.status_code, response.content, response.headers.get("Content-Type")

    @staticmethod
    def cookie_from(headers):
        return headers["set-cookie"].split(";", 1)[0]

    @classmethod
    def token_from_outbox(cls, email, parameter):
        entries = [json.loads(line) for line in (runtime.DATA_DIR / "outbox.log").read_text().splitlines()]
        message = next(
            entry for entry in reversed(entries) if entry["to"] == email and f"?{parameter}=" in entry["body"]
        )
        url = message["body"].strip().splitlines()[-1]
        return parse_qs(urlparse(url).query)[parameter][0]

    def test_account_verification_password_reset_and_audit(self):
        email = "security@example.test"
        account = {
            "email": email,
            "password": "original123",
            "displayName": "Чэнь Мин",
            "role": "student",
        }
        status, payload, headers = self.request("POST", "/api/auth/register", account)
        self.assertEqual(status, 201)
        self.assertFalse(payload["user"]["emailVerified"])
        cookie = self.cookie_from(headers)

        verification_token = self.token_from_outbox(email, "verify")
        status, _, _ = self.request("POST", "/api/auth/email/confirm", {"token": verification_token})
        self.assertEqual(status, 200)
        status, me, _ = self.request("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(me["user"]["emailVerified"])

        status, _, _ = self.request("POST", "/api/auth/password/request", {"email": email})
        self.assertEqual(status, 200)
        reset_token = self.token_from_outbox(email, "reset")
        status, _, _ = self.request(
            "POST", "/api/auth/password/reset", {"token": reset_token, "password": "replacement123"}
        )
        self.assertEqual(status, 200)
        status, _, _ = self.request("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(status, 401)
        status, _, _ = self.request("POST", "/api/auth/login", {"email": email, "password": "replacement123"})
        self.assertEqual(status, 200)

        status, _, headers = self.request("POST", "/api/auth/login", {"email": email, "password": "replacement123"})
        new_cookie = self.cookie_from(headers)
        status, audit, _ = self.request("GET", "/api/account/audit", cookie=new_cookie)
        self.assertEqual(status, 200)
        actions = {event["action"] for event in audit["events"]}
        self.assertIn("email_verified", actions)
        self.assertIn("password_reset_completed", actions)
        self.assertIn("login_succeeded", actions)

    def test_teacher_student_progress_flow(self):
        teacher = {
            "email": "teacher@example.test",
            "password": "teacher123",
            "displayName": "Ли Лаоши",
            "role": "teacher",
        }
        status, _, headers = self.request("POST", "/api/auth/register", teacher)
        self.assertEqual(status, 201)
        teacher_cookie = self.cookie_from(headers)

        status, blocked, _ = self.request("POST", "/api/teacher/groups", {"name": "11 класс"}, teacher_cookie)
        self.assertEqual(status, 403)
        self.assertEqual(blocked["code"], "email_verification_required")
        verification_token = self.token_from_outbox(teacher["email"], "verify")
        status, _, _ = self.request("POST", "/api/auth/email/confirm", {"token": verification_token})
        self.assertEqual(status, 200)

        student = {
            "email": "student@example.test",
            "password": "student123",
            "displayName": "Анна Петрова",
            "role": "student",
        }
        status, _, headers = self.request("POST", "/api/auth/register", student)
        self.assertEqual(status, 201)
        student_cookie = self.cookie_from(headers)

        status, group_payload, _ = self.request("POST", "/api/teacher/groups", {"name": "11 класс"}, teacher_cookie)
        self.assertEqual(status, 201)
        code = group_payload["group"]["code"]

        status, _, _ = self.request("POST", "/api/groups/join", {"code": code}, student_cookie)
        self.assertEqual(status, 200)
        status, invalid_assignment, _ = self.request(
            "POST",
            "/api/teacher/assignments",
            {
                "groupId": group_payload["group"]["id"],
                "title": "Несуществующий вариант",
                "variantId": "missing-variant",
                "tasks": [1],
                "dueAt": None,
            },
            teacher_cookie,
        )
        self.assertEqual(status, 400)
        self.assertEqual(invalid_assignment["code"], "invalid_assignment_material")
        status, assignment_payload, _ = self.request(
            "POST",
            "/api/teacher/assignments",
            {
                "groupId": group_payload["group"]["id"],
                "title": "Пробный вариант",
                "variantId": "demo-2026",
                "tasks": [1, 2],
                "dueAt": 1,
            },
            teacher_cookie,
        )
        self.assertEqual(status, 201)
        assignment_id = assignment_payload["assignment"]["id"]
        status, assignments, _ = self.request("GET", "/api/student/assignments", cookie=student_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(assignments["assignments"][0]["id"], assignment_id)
        self.assertEqual(assignments["assignments"][0]["material"]["id"], "demo-2026")
        self.assertFalse(assignments["assignments"][0]["materialUnavailable"])
        status, teacher_assignments, _ = self.request("GET", "/api/teacher/assignments", cookie=teacher_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(teacher_assignments["assignments"][0]["id"], assignment_id)
        status, _, _ = self.request(
            "PUT",
            f"/api/teacher/assignments/{assignment_id}",
            {"title": "Обновлённый вариант", "dueAt": 1},
            teacher_cookie,
        )
        self.assertEqual(status, 200)
        status, repeated, _ = self.request(
            "POST", f"/api/teacher/assignments/{assignment_id}/resend", {}, teacher_cookie
        )
        self.assertEqual(status, 201)
        self.assertNotEqual(repeated["assignment"]["id"], assignment_id)

        status, submission_payload, _ = self.request(
            "POST",
            f"/api/assignments/{assignment_id}/submissions",
            {"run": {"variantId": "demo-2026", "tasks": [1, 2]}},
            student_cookie,
        )
        self.assertEqual(status, 201)
        submission_id = submission_payload["submission"]["id"]
        self.assertTrue(submission_payload["submission"]["late"])
        status, recording_payload = self.request_audio(
            f"/api/submissions/{submission_id}/recordings?task=2&label=Answer", b"test-audio", student_cookie
        )
        self.assertEqual(status, 201)
        recording_id = recording_payload["recording"]["id"]
        status, audio_data, content_type = self.request_bytes(f"/api/recordings/{recording_id}", teacher_cookie)
        self.assertEqual(status, 200, audio_data)
        self.assertEqual(audio_data, b"test-audio")
        self.assertEqual(content_type, "audio/webm")

        status, teacher_submissions, _ = self.request("GET", "/api/teacher/submissions", cookie=teacher_cookie)
        self.assertEqual(status, 200)
        self.assertTrue(teacher_submissions["submissions"][0]["late"])
        self.assertEqual(teacher_submissions["submissions"][0]["recordings"][0]["id"], recording_id)
        status, history, _ = self.request("GET", f"/api/teacher/submissions/{submission_id}", cookie=teacher_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(history["attempts"][0]["id"], submission_id)
        status, csv_data, csv_type = self.request_bytes("/api/teacher/export.csv?status=submitted", teacher_cookie)
        self.assertEqual(status, 200)
        self.assertIn("text/csv", csv_type)
        self.assertIn("Обновлённый вариант".encode(), csv_data)
        review_scores = {
            "1": {"question1": 1, "question2": 1, "question3": 1, "question4": 1, "question5": 1},
            "2": {"content": 3, "organization": 2, "language": 2},
        }
        status, review, _ = self.request(
            "POST",
            f"/api/submissions/{submission_id}/review",
            {"scores": review_scores, "comment": "Отличная работа"},
            teacher_cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(review["review"], {"total": 12, "maximum": 12})
        progress = {
            "version": 1,
            "updatedAt": "2026-07-04T12:00:00.000Z",
            "settings": {},
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

        with runtime.connect() as database:
            file_name = database.execute("SELECT file_name FROM recordings WHERE id = ?", (recording_id,)).fetchone()[
                "file_name"
            ]
        audio_path = runtime.AUDIO_DIR / file_name
        self.assertTrue(audio_path.is_file())
        status, _, _ = self.request("DELETE", "/api/account", {"password": "student123"}, student_cookie)
        self.assertEqual(status, 200)
        self.assertFalse(audio_path.exists())
        status, _, _ = self.request("GET", "/api/auth/me", cookie=student_cookie)
        self.assertEqual(status, 401)
        with runtime.connect() as database:
            deleted = database.execute("SELECT id FROM users WHERE email = ?", (student["email"],)).fetchone()
            deletion_event = database.execute(
                "SELECT user_id FROM audit_log WHERE email = ? AND action = 'account_deleted'", (student["email"],)
            ).fetchone()
        self.assertIsNone(deleted)
        self.assertIsNone(deletion_event["user_id"])

    def test_teacher_registration_requires_allowlist(self):
        status, payload, _ = self.request(
            "POST",
            "/api/auth/register",
            {
                "email": "impostor@example.test",
                "password": "password123",
                "displayName": "Not a teacher",
                "role": "teacher",
            },
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "teacher_not_allowed")

    def test_migrations_are_recorded(self):
        with runtime.connect() as database:
            versions = [
                row["version"] for row in database.execute("SELECT version FROM schema_migrations ORDER BY version")
            ]
        self.assertEqual(versions, [1, 2, 3, 4, 5, 6, 7])
        with runtime.connect() as database:
            columns = {row["name"] for row in database.execute("PRAGMA table_info(assignments)")}
        self.assertIn("material_snapshot_json", columns)

    def test_mutation_without_origin_is_rejected(self):
        status, payload, _ = self.request(
            "POST",
            "/api/auth/login",
            {"email": "nobody@example.test", "password": "password123"},
            include_origin=False,
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "invalid_origin")
        self.assertEqual(payload["message"], "Invalid request origin")

    def test_login_endpoint_returns_rate_limit(self):
        payload = {"email": "rate-limit@example.test", "password": "password123"}
        for _ in range(8):
            status, _, _ = self.request("POST", "/api/auth/login", payload)
            self.assertEqual(status, 401)
        status, body, headers = self.request("POST", "/api/auth/login", payload)
        self.assertEqual(status, 429)
        self.assertIn("retry-after", headers)
        self.assertGreater(body["retryAfter"], 0)


if __name__ == "__main__":
    unittest.main()
