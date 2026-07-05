from fastapi import APIRouter, Request

from api.http import invoke
from api.schemas import (
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
    return await invoke(request, "auth_register", payload=payload)


@router.post("/auth/login")
async def login(request: Request, payload: LoginRequest):
    return await invoke(request, "auth_login", payload=payload)


@router.post("/auth/logout")
async def logout(request: Request):
    return await invoke(request, "auth_logout")


@router.get("/auth/me")
async def me(request: Request):
    return await invoke(request, "auth_me")


@router.post("/auth/email/request")
async def request_email_verification(request: Request):
    return await invoke(request, "email_verification_request")


@router.post("/auth/email/confirm")
async def confirm_email(request: Request, payload: TokenRequest):
    return await invoke(request, "email_verification_confirm", payload=payload)


@router.post("/auth/password/request")
async def request_password_reset(request: Request, payload: EmailRequest):
    return await invoke(request, "password_reset_request", payload=payload)


@router.post("/auth/password/reset")
async def reset_password(request: Request, payload: PasswordResetRequest):
    return await invoke(request, "password_reset_confirm", payload=payload)


@router.get("/account/audit")
async def account_audit(request: Request):
    return await invoke(request, "account_audit")


@router.delete("/account")
async def delete_account(request: Request, payload: DeleteAccountRequest):
    return await invoke(request, "account_delete", payload=payload)
