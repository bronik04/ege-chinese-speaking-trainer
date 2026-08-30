from __future__ import annotations

from http import HTTPStatus

from trainer.api import runtime
from trainer.api.dependencies import owner_email_from_env
from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import ActionResult, RequestContext
from trainer.api.schemas import ReviewRequestCreate, ReviewScoresRequest
from trainer.services.review_request_repository import RequestMetadata, ReviewActor
from trainer.services.review_requests import ReviewRequestError


def _service_error(error: ReviewRequestError) -> ApiError:
    if error.reason == "invalid_request":
        return ApiError(default_error_code(HTTPStatus.BAD_REQUEST), error.message, HTTPStatus.BAD_REQUEST)
    if error.reason == "run_too_large":
        return ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST),
            "Данные попытки слишком велики",
            HTTPStatus.BAD_REQUEST,
        )
    if error.reason == "invalid_material":
        return ApiError(
            "invalid_review_material",
            "Материал не найден или не содержит выбранные задания",
            HTTPStatus.BAD_REQUEST,
        )
    if error.reason == "unsupported_media_type":
        return ApiError(
            default_error_code(HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
            "Неподдерживаемый формат аудио",
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        )
    if error.reason == "recording_too_large":
        return ApiError(
            default_error_code(HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
            "Запись превышает 15 МБ",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    if error.reason == "invalid_audio":
        return ApiError(
            default_error_code(HTTPStatus.UNPROCESSABLE_ENTITY),
            "Некорректная или слишком длинная аудиозапись",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if error.reason == "not_found":
        return ApiError(
            "review_request_not_found",
            error.message or "Запрос не найден",
            HTTPStatus.NOT_FOUND,
            **error.details,
        )
    if error.reason == "not_uploading":
        return ApiError(
            "review_request_not_uploading",
            error.message or "Запрос уже отправлен",
            HTTPStatus.CONFLICT,
            **error.details,
        )
    if error.reason == "incomplete":
        return ApiError(
            "review_request_incomplete",
            "Загрузите все обязательные записи",
            HTTPStatus.CONFLICT,
            **error.details,
        )
    if error.reason == "invalid_scores":
        return ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST),
            error.message,
            HTTPStatus.BAD_REQUEST,
            **error.details,
        )
    raise error


def _owner_allowed(user: dict) -> bool:
    return bool(
        user.get("role") == "teacher"
        and user.get("emailVerified")
        and str(user.get("email", "")).strip().lower() == owner_email_from_env()
    )


def review_request_create(payload: ReviewRequestCreate, user: dict, context: RequestContext) -> ActionResult:
    try:
        result = runtime.review_request_service().create(
            kind=payload.kind,
            tasks=payload.tasks,
            variant_id=payload.variantId.strip(),
            run=payload.run,
            actor=ReviewActor(id=user["id"], email=user["email"]),
            metadata=RequestMetadata(client_ip=context.client_ip, user_agent=context.user_agent),
        )
    except ReviewRequestError as error:
        raise _service_error(error) from error
    return ActionResult(result, status=HTTPStatus.CREATED)


def review_recording_create(
    request_id: int,
    query: dict,
    body: bytes,
    content_type: str,
    user: dict,
    context: RequestContext,
) -> ActionResult:
    try:
        task = int(query.get("task") or "")
        question_value = query.get("question")
        question = int(question_value) if question_value else None
    except (TypeError, ValueError) as error:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Некорректный номер записи", HTTPStatus.BAD_REQUEST
        ) from error
    label = str(query.get("label") or f"Задание {task}")[:160]
    mime_type = content_type.split(";", 1)[0].lower()
    try:
        result = runtime.review_request_service().upload_recording(
            request_id=request_id,
            task=task,
            question=question,
            label=label,
            mime_type=mime_type,
            body=body,
            actor=ReviewActor(id=user["id"], email=user["email"]),
            metadata=RequestMetadata(client_ip=context.client_ip, user_agent=context.user_agent),
        )
    except ReviewRequestError as error:
        raise _service_error(error) from error
    return ActionResult(result, status=HTTPStatus.CREATED)


def review_request_complete(request_id: int, user: dict, context: RequestContext) -> ActionResult:
    try:
        result = runtime.review_request_service().complete(
            request_id,
            actor=ReviewActor(id=user["id"], email=user["email"]),
            metadata=RequestMetadata(client_ip=context.client_ip, user_agent=context.user_agent),
        )
    except ReviewRequestError as error:
        raise _service_error(error) from error
    return ActionResult(result)


def review_request_discard(request_id: int, user: dict, context: RequestContext) -> ActionResult:
    try:
        result = runtime.review_request_service().discard(
            request_id,
            actor=ReviewActor(id=user["id"], email=user["email"]),
            metadata=RequestMetadata(client_ip=context.client_ip, user_agent=context.user_agent),
        )
    except ReviewRequestError as error:
        raise _service_error(error) from error
    return ActionResult(result)


def student_review_requests(user: dict) -> ActionResult:
    return ActionResult({"requests": runtime.review_request_service().student_requests(user["id"])})


def teacher_review_requests(query: dict) -> ActionResult:
    try:
        task = int(query.get("task") or 0) or None
    except (TypeError, ValueError):
        task = None
    try:
        submitted_from = int(query.get("submittedFrom")) if query.get("submittedFrom") is not None else None
        submitted_before = int(query.get("submittedBefore")) if query.get("submittedBefore") is not None else None
    except (TypeError, ValueError):
        submitted_from = submitted_before = None
    requests = runtime.review_request_service().teacher_requests(
        student=str(query.get("student") or "").strip(),
        task=task,
        status=str(query.get("status") or "").strip(),
        submitted_from=submitted_from,
        submitted_before=submitted_before,
    )
    return ActionResult({"requests": requests})


def teacher_review_request_detail(request_id: int, user: dict) -> ActionResult:
    if not _owner_allowed(user):
        raise ApiError("review_request_not_found", "Запрос не найден", HTTPStatus.NOT_FOUND)
    try:
        result = runtime.review_request_service().teacher_detail(request_id)
    except ReviewRequestError as error:
        raise _service_error(error) from error
    return ActionResult({"reviewRequest": result})


def teacher_review_request_score(
    request_id: int,
    payload: ReviewScoresRequest,
    user: dict,
    context: RequestContext,
) -> ActionResult:
    try:
        result = runtime.review_request_service().score(
            request_id,
            payload.scores,
            actor=ReviewActor(id=user["id"], email=user["email"]),
            metadata=RequestMetadata(client_ip=context.client_ip, user_agent=context.user_agent),
        )
    except ReviewRequestError as error:
        raise _service_error(error) from error
    return ActionResult(result)
