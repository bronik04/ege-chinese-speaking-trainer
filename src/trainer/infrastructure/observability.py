from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import UTC, datetime

_request_id = contextvars.ContextVar("request_id", default="")


def current_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str | None = None):
    return _request_id.set(value or uuid.uuid4().hex)


def reset_request_id(token) -> None:
    _request_id.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
            "requestId": current_request_id() or None,
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_trainer_json_logging", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.environ.get("TRAINER_LOG_LEVEL", "INFO").upper())
    root._trainer_json_logging = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def log_event(logger: logging.Logger, level: int, event: str, message: str, **fields: object) -> None:
    logger.log(level, message, extra={"event": event, "fields": fields})


class ErrorMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._responses_4xx = 0
        self._responses_5xx = 0
        self._last_failure_at: int | None = None

    def observe(self, status: int) -> None:
        with self._lock:
            if 400 <= status < 500:
                self._responses_4xx += 1
            elif status >= 500:
                self._responses_5xx += 1
                self._last_failure_at = int(time.time())

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "responses4xx": self._responses_4xx,
                "responses5xx": self._responses_5xx,
                "lastFailureAt": self._last_failure_at,
            }


error_monitor = ErrorMonitor()
