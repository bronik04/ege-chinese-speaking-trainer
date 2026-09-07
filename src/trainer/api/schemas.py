from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from trainer.domain.progress import ProgressValidationError, normalize_progress, parse_completed_run


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RegisterRequest(ApiSchema):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    displayName: str = Field(min_length=2, max_length=80)


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


class StrictProgressSchema(ApiSchema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)


class ProgressSettings(StrictProgressSchema):
    lastVariant: StrictStr | None = Field(default=None, min_length=1, max_length=80)
    fastMode: StrictBool


class ActiveRun(StrictProgressSchema):
    id: StrictStr = Field(min_length=1, max_length=120)
    variantId: StrictStr = Field(min_length=1, max_length=80)
    variantLabel: StrictStr = Field(min_length=1, max_length=160)
    mode: Literal["exam", "practice"]
    tasks: list[Literal[1, 2, 3]] = Field(min_length=1, max_length=3)
    completedTasks: list[Literal[1, 2, 3]] = Field(max_length=3)
    currentTask: Literal[1, 2, 3]
    phase: Literal["idle", "prep", "answer"]
    fastMode: StrictBool
    startedAt: StrictStr = Field(min_length=20, max_length=40)


class CompletedRun(ActiveRun):
    status: Literal["completed", "interrupted"]
    completedAt: StrictStr = Field(min_length=20, max_length=40)
    recordingsCount: StrictInt = Field(ge=0, le=100)


class ProgressV2(StrictProgressSchema):
    version: Literal[2]
    updatedAt: StrictStr = Field(min_length=20, max_length=40)
    settings: ProgressSettings
    runs: list[CompletedRun] = Field(max_length=100)
    activeRun: ActiveRun | None

    @model_validator(mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not dict or type(value.get("version")) is not int or value["version"] != 2:
            raise ValueError("version must be the integer 2")
        return value

    @model_validator(mode="after")
    def valid_domain_contract(self):
        try:
            normalize_progress(self.model_dump(mode="json", by_alias=True))
        except ProgressValidationError as error:
            raise ValueError(error.reason) from error
        return self


class ProgressV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: Literal[1]

    @model_validator(mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not dict or type(value.get("version")) is not int or value["version"] != 1:
            raise ValueError("version must be the integer 1")
        return value


ProgressPayload = Annotated[ProgressV1 | ProgressV2, Field(discriminator="version")]


class ProgressRequest(ApiSchema):
    progress: ProgressPayload


class PersonalRecordingUpload(ApiSchema):
    runId: str = Field(min_length=1, max_length=120)
    variantId: str = Field(pattern=r"^[a-z0-9-]{3,50}$")
    taskNumber: int = Field(ge=1, le=3)
    questionNumber: int = Field(ge=1, le=5)
    label: str = Field(min_length=1, max_length=160)


class ReviewRequestCreate(ApiSchema):
    kind: Literal["task", "attempt"]
    variantId: str = Field(pattern=r"^[a-z0-9-]{3,50}$")
    tasks: list[Literal[1, 2, 3]] = Field(min_length=1, max_length=3)
    run: CompletedRun

    @model_validator(mode="after")
    def valid_run_contract(self):
        try:
            parse_completed_run(self.run.model_dump(mode="json", by_alias=True))
        except ProgressValidationError as error:
            raise ValueError(error.reason) from error
        return self


class ReviewScoresRequest(ApiSchema):
    scores: dict[str, dict[str, int]]


class MaterialRequest(ApiSchema):
    slug: str = Field(pattern=r"^[a-z0-9-]{3,50}$")
    kind: Literal["full", "task"]
    taskNumber: Literal[1, 2, 3] | None = None
    title: str = Field(min_length=2, max_length=120)
    year: int = Field(ge=2020, le=2100)
    source: str = Field(min_length=2, max_length=200)
    content: dict[str, Any] = Field(default_factory=dict)
