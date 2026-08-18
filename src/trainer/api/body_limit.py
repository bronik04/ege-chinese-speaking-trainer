from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import JSONResponse

from trainer.api.errors import error_payload


class RequestBodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], limit_for_request: Callable[[str, str], int | None]):
        self.app = app
        self.limit_for_request = limit_for_request

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for_request(scope["method"], scope["path"])
        if limit is None:
            await self.app(scope, receive, send)
            return
        received = 0
        exceeded = False
        response_sent = False

        async def send_too_large() -> None:
            nonlocal response_sent
            if response_sent:
                return
            response_sent = True
            response = JSONResponse(error_payload("request_too_large", "Request body is too large"), status_code=413)
            await response(scope, receive, send)

        async def limited_receive():
            nonlocal exceeded, received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise RequestBodyTooLarge
            return message

        async def limited_send(message):
            if exceeded:
                await send_too_large()
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except RequestBodyTooLarge:
            await send_too_large()
