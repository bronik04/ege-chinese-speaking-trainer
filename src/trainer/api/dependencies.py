from __future__ import annotations

import os
from http import HTTPStatus
from http.cookies import SimpleCookie

from fastapi import Request

from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import RequestContext
from trainer.api.runtime import DATA_DIR, SESSION_DAYS, connect
from trainer.domain.accounts import authorize_role, validate_credentials
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


class ApiDependenciesMixin:
    def create_session(self, user_id: int) -> str:
        return account_services.create_session(connect, user_id, SESSION_DAYS)

    def current_user(self) -> dict | None:
        return account_services.current_user(connect, self.session_token())

    @staticmethod
    def user_payload(user_id: int, email: str, display_name: str, role: str, email_verified_at: int | None) -> dict:
        return account_services.user_payload(user_id, email, display_name, role, email_verified_at)

    @staticmethod
    def user_for_token(database, token: str):
        return account_services.user_for_token(database, token)

    def audit(
        self,
        database,
        action: str,
        *,
        user_id: int | None = None,
        email: str | None = None,
        details: dict | None = None,
    ) -> None:
        account_services.audit(
            database,
            action,
            client_ip=self.client_address[0],
            user_agent=self.headers.get("User-Agent", ""),
            user_id=user_id,
            email=email,
            details=details,
        )

    def send_account_link(self, kind: str, email: str, token: str) -> str:
        return account_services.send_account_link(
            connect,
            DATA_DIR,
            kind,
            email,
            token,
            public_url=account_public_url(),
            client_ip=self.client_address[0],
            user_agent=self.headers.get("User-Agent", ""),
        )

    def require_role(self, role: str) -> dict | None:
        user = self.current_user()
        decision = authorize_role(
            user,
            role,
            teacher_emails=os.environ.get("TRAINER_TEACHER_EMAILS", ""),
        )
        if not decision.allowed:
            status = HTTPStatus.UNAUTHORIZED if decision.code == "authentication_required" else HTTPStatus.FORBIDDEN
            public_code = (
                decision.code if decision.code in {"email_verification_required", "teacher_not_allowed"} else None
            )
            self.send_error_json(status, decision.message, public_code)
            return None
        return user

    def session_token(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("trainer_session")
        return morsel.value if morsel else None

    def validate_credentials(self, payload: dict) -> tuple[str, str, str | None]:
        return validate_credentials(payload.get("email", ""), payload.get("password", ""))
