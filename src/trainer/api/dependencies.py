from __future__ import annotations

import os
from http.cookies import SimpleCookie

from fastapi import Request

from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import RequestContext
from trainer.api.runtime import connect
from trainer.domain.accounts import authorize_role
from trainer.domain.materials import editor_allowed
from trainer.services import accounts as account_services


def account_public_url() -> str:
    return os.environ.get("TRAINER_PUBLIC_URL", "").rstrip("/") or "http://127.0.0.1:8080"


def session_token(request: Request) -> str | None:
    cookie = SimpleCookie(request.headers.get("Cookie", ""))
    morsel = cookie.get("trainer_session")
    return morsel.value if morsel else None


def request_context(request: Request) -> RequestContext:
    return RequestContext(
        client_ip=request.client.host if request.client else "",
        user_agent=request.headers.get("User-Agent", ""),
    )


def current_user_or_none(request: Request) -> dict | None:
    return account_services.current_user(connect, session_token(request))


def _require_role(request: Request, role: str) -> dict:
    user = current_user_or_none(request)
    decision = authorize_role(
        user,
        role,
        teacher_emails=os.environ.get("TRAINER_TEACHER_EMAILS", ""),
    )
    if not decision.allowed:
        status = 401 if decision.code == "authentication_required" else 403
        public_code = (
            decision.code
            if decision.code in {"email_verification_required", "teacher_not_allowed"}
            else default_error_code(status)
        )
        raise ApiError(public_code, decision.message, status)
    return user


def require_student(request: Request) -> dict:
    return _require_role(request, "student")


def require_teacher(request: Request) -> dict:
    return _require_role(request, "teacher")


def require_authenticated(request: Request) -> dict:
    user = current_user_or_none(request)
    if not user:
        raise ApiError("authentication_required", "Authentication required", 401)
    return user


def require_material_editor(request: Request) -> dict:
    user = current_user_or_none(request)
    if not user:
        raise ApiError("authentication_required", "Войдите, чтобы создавать материалы", 401)
    if not user["emailVerified"]:
        raise ApiError("email_verification_required", "Подтвердите email для работы с материалами", 403)
    if not editor_allowed(user, os.environ.get("TRAINER_EDITOR_EMAILS", "")):
        raise ApiError("editor_forbidden", "Создание материалов недоступно", 403)
    return user
