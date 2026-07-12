from __future__ import annotations

import os
from http import HTTPStatus
from http.cookies import SimpleCookie

from trainer.api.runtime import DATA_DIR, SESSION_DAYS, connect
from trainer.domain.accounts import authorize_role, validate_credentials
from trainer.services import accounts as account_services


def account_public_url() -> str:
    return os.environ.get("TRAINER_PUBLIC_URL", "").rstrip("/") or "http://127.0.0.1:8080"


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
