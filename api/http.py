from __future__ import annotations

import io
from types import MethodType

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from api.controller import ApiController
from api.errors import error_payload
from api.runtime import MAX_AUDIO_BODY, MAX_BODY


def _bind(controller, name, function) -> None:
    setattr(controller, name, MethodType(function, controller))


async def invoke(request: Request, action: str, *arguments, payload: BaseModel | None = None) -> Response:
    max_body = MAX_AUDIO_BODY if action in {"recording_create", "material_asset_create"} else MAX_BODY
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_body:
            return JSONResponse(error_payload("request_too_large", "Request body is too large"), status_code=413)

    controller = object.__new__(ApiController)
    controller.path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    controller.headers = request.headers
    controller.client_address = (request.client.host if request.client else "", 0)
    controller.rfile = io.BytesIO(body)
    controller.wfile = io.BytesIO()
    controller.validated_payload = payload.model_dump(by_alias=True) if payload is not None else None
    state = {"status": 200, "headers": []}
    _bind(controller, "send_response", lambda self, status, message=None: state.update(status=int(status)))
    _bind(controller, "send_header", lambda self, name, value: state["headers"].append((name, value)))
    _bind(controller, "end_headers", lambda self: None)

    if request.method in {"POST", "PUT", "DELETE"} and not controller.same_origin_request():
        controller.send_error_json(403, "Invalid request origin", "invalid_origin")
    else:
        getattr(controller, action)(*arguments)
    return Response(
        content=controller.wfile.getvalue(),
        status_code=state["status"],
        headers=dict(state["headers"]),
    )
