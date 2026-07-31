from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from trainer.api.controllers import auth as actions
from trainer.api.dependencies import current_user_or_none, request_context, require_authenticated, session_token
from trainer.api.routes import respond
from trainer.api.schemas import (
    DeleteAccountRequest,
    EmailRequest,
    LoginRequest,
    PasswordResetRequest,
    RegisterRequest,
    TokenRequest,
)

router = APIRouter(prefix="/api")


@router.post("/auth/register")
async def register(request: Request, payload: RegisterRequest):
    result = await run_in_threadpool(actions.auth_register, payload, request_context(request))
    return respond(result)


@router.post("/auth/login")
async def login(request: Request, payload: LoginRequest):
    result = await run_in_threadpool(actions.auth_login, payload, request_context(request))
    return respond(result)


@router.post("/auth/logout")
async def logout(request: Request):
    result = await run_in_threadpool(actions.auth_logout, session_token(request), request_context(request))
    return respond(result)


@router.get("/auth/me")
async def me(request: Request):
    result = await run_in_threadpool(actions.auth_me, current_user_or_none(request))
    return respond(result)


@router.post("/auth/email/request")
async def request_email_verification(request: Request, user: dict = Depends(require_authenticated)):
    result = await run_in_threadpool(actions.email_verification_request, user, request_context(request))
    return respond(result)


@router.post("/auth/email/confirm")
async def confirm_email(request: Request, payload: TokenRequest):
    result = await run_in_threadpool(actions.email_verification_confirm, payload, request_context(request))
    return respond(result)


@router.post("/auth/password/request")
async def request_password_reset(request: Request, payload: EmailRequest):
    result = await run_in_threadpool(actions.password_reset_request, payload, request_context(request))
    return respond(result)


@router.post("/auth/password/reset")
async def reset_password(request: Request, payload: PasswordResetRequest):
    result = await run_in_threadpool(actions.password_reset_confirm, payload, request_context(request))
    return respond(result)


@router.get("/account/audit")
async def account_audit(user: dict = Depends(require_authenticated)):
    result = await run_in_threadpool(actions.account_audit, user)
    return respond(result)


@router.delete("/account")
async def delete_account(request: Request, payload: DeleteAccountRequest, user: dict = Depends(require_authenticated)):
    result = await run_in_threadpool(actions.account_delete, payload, user, request_context(request))
    return respond(result)
