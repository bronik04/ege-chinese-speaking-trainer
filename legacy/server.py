#!/usr/bin/env python3
"""Legacy compatibility HTTP server; production uses FastAPI routes from asgi.py."""

from __future__ import annotations

import argparse
import logging
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from trainer.api.controller import ApiController
from trainer.api.runtime import AUDIO_DIR, DATA_DIR, DB_PATH, MAX_AUDIO_BODY, MAX_BODY, ROOT, connect, init_database
from trainer.infrastructure.database.core import engine_name
from trainer.infrastructure.observability import configure_logging, error_monitor, log_event

__all__ = [
    "AUDIO_DIR",
    "DATA_DIR",
    "DB_PATH",
    "MAX_AUDIO_BODY",
    "MAX_BODY",
    "ROOT",
    "ThreadingHTTPServer",
    "TrainerHandler",
    "connect",
    "init_database",
]


class TrainerHandler(BaseHTTPRequestHandler, ApiController):
    server_version = "ChineseEGETrainer/1.0"

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/health":
            self.send_json({"ok": True, "database": engine_name(), "errors": error_monitor.snapshot()})
        elif route == "/api/auth/me":
            self.auth_me()
        elif route == "/api/progress":
            self.progress_get()
        elif route == "/api/teacher/dashboard":
            self.teacher_dashboard()
        elif route == "/api/student/groups":
            self.student_groups()
        elif route == "/api/student/assignments":
            self.student_assignments()
        elif route == "/api/teacher/submissions":
            self.teacher_submissions()
        elif route == "/api/teacher/assignments":
            self.teacher_assignments()
        elif match := re.fullmatch(r"/api/teacher/submissions/(\d+)", route):
            self.submission_history(int(match.group(1)))
        elif route == "/api/teacher/export.csv":
            self.teacher_export("csv")
        elif route == "/api/teacher/export.pdf":
            self.teacher_export("pdf")
        elif route == "/api/account/audit":
            self.account_audit()
        elif route == "/api/materials":
            self.materials_list()
        elif route == "/api/materials/mine":
            self.materials_mine()
        elif match := re.fullmatch(r"/api/materials/([a-z0-9-]+)", route):
            self.material_get(match.group(1))
        elif match := re.fullmatch(r"/api/material-assets/(\d+)", route):
            self.material_asset_get(int(match.group(1)))
        elif re.fullmatch(r"/api/recordings/\d+", route):
            self.recording_get(int(route.rsplit("/", 1)[1]))
        elif route.startswith("/api/"):
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found", "route_not_found")
        else:
            self.serve_static(route)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if not self.same_origin_request():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid request origin", "invalid_origin")
        elif route == "/api/auth/register":
            self.auth_register()
        elif route == "/api/auth/login":
            self.auth_login()
        elif route == "/api/auth/logout":
            self.auth_logout()
        elif route == "/api/auth/email/request":
            self.email_verification_request()
        elif route == "/api/auth/email/confirm":
            self.email_verification_confirm()
        elif route == "/api/auth/password/request":
            self.password_reset_request()
        elif route == "/api/auth/password/reset":
            self.password_reset_confirm()
        elif route == "/api/teacher/groups":
            self.teacher_group_create()
        elif route == "/api/groups/join":
            self.group_join()
        elif route == "/api/teacher/assignments":
            self.teacher_assignment_create()
        elif match := re.fullmatch(r"/api/teacher/assignments/(\d+)/resend", route):
            self.teacher_assignment_resend(int(match.group(1)))
        elif match := re.fullmatch(r"/api/assignments/(\d+)/submissions", route):
            self.submission_create(int(match.group(1)))
        elif match := re.fullmatch(r"/api/submissions/(\d+)/recordings", route):
            self.recording_create(int(match.group(1)))
        elif match := re.fullmatch(r"/api/submissions/(\d+)/review", route):
            self.review_submission(int(match.group(1)))
        elif route == "/api/materials":
            self.material_create()
        elif match := re.fullmatch(r"/api/materials/([a-z0-9-]+)/publish", route):
            self.material_publish(match.group(1))
        elif match := re.fullmatch(r"/api/materials/([a-z0-9-]+)/assets", route):
            self.material_asset_create(match.group(1))
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found", "route_not_found")

    def do_DELETE(self) -> None:
        route = urlparse(self.path).path
        if not self.same_origin_request():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid request origin", "invalid_origin")
        elif route == "/api/account":
            self.account_delete()
        elif match := re.fullmatch(r"/api/materials/([a-z0-9-]+)", route):
            self.material_delete(match.group(1))
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found", "route_not_found")

    def do_PUT(self) -> None:
        route = urlparse(self.path).path
        if not self.same_origin_request():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid request origin", "invalid_origin")
        elif route == "/api/progress":
            self.progress_put()
        elif match := re.fullmatch(r"/api/teacher/assignments/(\d+)", route):
            self.teacher_assignment_update(int(match.group(1)))
        elif match := re.fullmatch(r"/api/materials/([a-z0-9-]+)", route):
            self.material_update(match.group(1))
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found", "route_not_found")


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Local compatibility server for the Chinese EGE speaking trainer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args()
    init_database()
    server = ThreadingHTTPServer((args.host, args.port), TrainerHandler)
    log_event(
        logging.getLogger("trainer.compat_http"),
        logging.INFO,
        "server_started",
        "Compatibility server started",
        host=args.host,
        port=args.port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
