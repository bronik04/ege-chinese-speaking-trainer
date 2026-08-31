from __future__ import annotations

from http import HTTPStatus

from trainer.api import runtime
from trainer.api.errors import ApiError
from trainer.api.results import ActionResult, RequestContext
from trainer.api.schemas import (
    DeleteAccountRequest,
    EmailRequest,
    LoginRequest,
    PasswordResetRequest,
    RegisterRequest,
    TokenRequest,
)
from trainer.services.account_repository import AccountRequestMetadata
from trainer.services.accounts import AccountError

_ERROR_STATUS_AND_CODE = {
    "invalid_input": (HTTPStatus.BAD_REQUEST, "invalid_request"),
    "email_already_registered": (HTTPStatus.CONFLICT, "email_already_registered"),
    "invalid_credentials": (HTTPStatus.UNAUTHORIZED, "invalid_credentials"),
    "email_already_verified": (HTTPStatus.CONFLICT, "email_already_verified"),
    "token_invalid": (HTTPStatus.BAD_REQUEST, "token_invalid"),
    "invalid_password": (HTTPStatus.UNAUTHORIZED, "invalid_password"),
    "rate_limited": (HTTPStatus.TOO_MANY_REQUESTS, "rate_limited"),
}


def _metadata(context: RequestContext) -> AccountRequestMetadata:
    return AccountRequestMetadata(context.client_ip, context.user_agent)


def _api_error(error: AccountError) -> ApiError:
    status, code = _ERROR_STATUS_AND_CODE.get(
        error.reason,
        (HTTPStatus.BAD_REQUEST, "invalid_request"),
    )
    if error.reason == "rate_limited" and error.retry_after is not None:
        return ApiError(
            code,
            error.message,
            status,
            headers={"Retry-After": str(error.retry_after)},
            retryAfter=error.retry_after,
        )
    return ApiError(code, error.message, status)


def auth_register(payload: RegisterRequest, context: RequestContext) -> ActionResult:
    try:
        result = runtime.account_service().register(
            payload.email,
            payload.password,
            payload.displayName,
            _metadata(context),
        )
    except AccountError as error:
        raise _api_error(error) from error
    return ActionResult(
        {"user": result.user, "verificationDelivery": result.verification_delivery},
        status=HTTPStatus.CREATED,
        session_token=result.session_token,
    )


def auth_login(payload: LoginRequest, context: RequestContext) -> ActionResult:
    try:
        result = runtime.account_service().login(payload.email, payload.password, _metadata(context))
    except AccountError as error:
        raise _api_error(error) from error
    return ActionResult({"user": result.user}, session_token=result.session_token)


def auth_logout(token: str | None, context: RequestContext) -> ActionResult:
    try:
        runtime.account_service().logout(token, _metadata(context))
    except AccountError as error:
        raise _api_error(error) from error
    return ActionResult({"ok": True}, clear_session=True)


def auth_me(user: dict | None) -> ActionResult:
    if not user:
        raise ApiError("authentication_required", "Authentication required", HTTPStatus.UNAUTHORIZED)
    return ActionResult({"user": user})


def email_verification_request(user: dict, context: RequestContext) -> ActionResult:
    try:
        delivery = runtime.account_service().request_email_verification(
            user["id"], user["email"], user["emailVerified"], _metadata(context)
        )
    except AccountError as error:
        raise _api_error(error) from error
    return ActionResult({"ok": True, "delivery": delivery})


def email_verification_confirm(payload: TokenRequest, context: RequestContext) -> ActionResult:
    try:
        runtime.account_service().confirm_email_verification(payload.token, _metadata(context))
    except AccountError as error:
        raise _api_error(error) from error
    return ActionResult({"ok": True})


def password_reset_request(payload: EmailRequest, context: RequestContext) -> ActionResult:
    try:
        runtime.account_service().request_password_reset(payload.email, _metadata(context))
    except AccountError as error:
        raise _api_error(error) from error
    return ActionResult({"ok": True, "message": "Если аккаунт существует, инструкция отправлена"})


def password_reset_confirm(payload: PasswordResetRequest, context: RequestContext) -> ActionResult:
    try:
        runtime.account_service().confirm_password_reset(payload.token, payload.password, _metadata(context))
    except AccountError as error:
        raise _api_error(error) from error
    return ActionResult({"ok": True}, clear_session=True)


def account_audit(user: dict) -> ActionResult:
    return ActionResult({"events": runtime.account_service().audit_events(user["id"])})


def account_delete(payload: DeleteAccountRequest, user: dict, context: RequestContext) -> ActionResult:
    try:
        runtime.account_service().delete_account(user["id"], user["email"], payload.password, _metadata(context))
    except AccountError as error:
        raise _api_error(error) from error
    return ActionResult({"ok": True}, clear_session=True)
