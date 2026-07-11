from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RegisterRequest(ApiSchema):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    displayName: str = Field(min_length=2, max_length=80)
    role: Literal["student", "teacher"] = "student"


class LoginRequest(ApiSchema):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class EmailRequest(ApiSchema):
    email: str = Field(min_length=3, max_length=254)


class TokenRequest(ApiSchema):
    token: str = Field(min_length=1, max_length=256)


class PasswordResetRequest(TokenRequest):
    password: str = Field(min_length=8, max_length=128)


class DeleteAccountRequest(ApiSchema):
    password: str = Field(min_length=1, max_length=128)


class ProgressRequest(ApiSchema):
    progress: dict[str, Any]


class GroupRequest(ApiSchema):
    name: str = Field(min_length=2, max_length=80)


class JoinGroupRequest(ApiSchema):
    code: str = Field(min_length=6, max_length=16)


class AssignmentRequest(ApiSchema):
    groupId: int = Field(ge=1)
    title: str = Field(min_length=2, max_length=100)
    variantId: str = Field(pattern=r"^[a-z0-9-]{3,40}$")
    tasks: list[Literal[1, 2, 3]] = Field(min_length=1, max_length=3)
    dueAt: int | None = None


class AssignmentUpdateRequest(ApiSchema):
    title: str = Field(min_length=2, max_length=100)
    dueAt: int | None = None


class SubmissionRequest(ApiSchema):
    run: dict[str, Any]


class ReviewRequest(ApiSchema):
    scores: dict[str, dict[str, int]]
    comment: str = Field(default="", max_length=3000)


class MaterialRequest(ApiSchema):
    slug: str = Field(pattern=r"^[a-z0-9-]{3,50}$")
    kind: Literal["full", "task"]
    taskNumber: Literal[1, 2, 3] | None = None
    title: str = Field(min_length=2, max_length=120)
    year: int = Field(ge=2020, le=2100)
    source: str = Field(min_length=2, max_length=200)
    content: dict[str, Any] = Field(default_factory=dict)
