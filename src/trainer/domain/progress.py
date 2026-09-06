import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, cast

TaskNumber = Literal[1, 2, 3]
Mode = Literal["exam", "practice"]
Phase = Literal["idle", "prep", "answer"]
RunStatus = Literal["completed", "interrupted"]

ROOT_FIELDS = frozenset({"version", "updatedAt", "settings", "runs", "activeRun"})
SETTINGS_FIELDS = frozenset({"lastVariant", "fastMode"})
RUN_FIELDS = frozenset(
    {
        "id",
        "variantId",
        "variantLabel",
        "mode",
        "tasks",
        "completedTasks",
        "currentTask",
        "phase",
        "fastMode",
        "startedAt",
    }
)
COMPLETED_FIELDS = RUN_FIELDS | {"status", "completedAt", "recordingsCount"}
EPOCH = "1970-01-01T00:00:00.000Z"
RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")


class ProgressValidationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ProgressSettings:
    last_variant: str | None
    fast_mode: bool


@dataclass(frozen=True)
class ProgressRun:
    id: str
    variant_id: str
    variant_label: str
    mode: Mode
    tasks: tuple[TaskNumber, ...]
    completed_tasks: tuple[TaskNumber, ...]
    current_task: TaskNumber
    phase: Phase
    fast_mode: bool
    started_at: str


@dataclass(frozen=True)
class CompletedProgressRun(ProgressRun):
    status: RunStatus
    completed_at: str
    recordings_count: int


@dataclass(frozen=True)
class ProgressDocument:
    updated_at: str
    settings: ProgressSettings
    runs: tuple[CompletedProgressRun, ...]
    active_run: ProgressRun | None
    version: Literal[2] = 2


def _invalid() -> ProgressValidationError:
    return ProgressValidationError("invalid_document")


def _object(value: object, fields: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != fields:
        raise _invalid()
    return value


def _string(value: object, *, minimum: int, maximum: int) -> str:
    if type(value) is not str or not minimum <= len(value) <= maximum:
        raise _invalid()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise _invalid()
    return value


def _integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid()
    return value


def _task(value: object) -> TaskNumber:
    return cast(TaskNumber, _integer(value, minimum=1, maximum=3))


def _tasks(value: object, *, allow_empty: bool) -> tuple[TaskNumber, ...]:
    if type(value) is not list or len(value) > 3 or (not allow_empty and not value):
        raise _invalid()
    tasks = tuple(_task(item) for item in value)
    if len(set(tasks)) != len(tasks):
        raise _invalid()
    return tuple(sorted(tasks))


def _timestamp(value: object) -> tuple[str, datetime]:
    if type(value) is not str or RFC3339_RE.fullmatch(value) is None:
        raise _invalid()
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise _invalid() from error
    if parsed.tzinfo is None:
        raise _invalid()
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"), utc


def _choice(value: object, allowed: tuple[str, ...]) -> str:
    if type(value) is not str or value not in allowed:
        raise _invalid()
    return value


def _parse_run_fields(value: object, fields: frozenset[str]) -> tuple[ProgressRun, datetime]:
    document = _object(value, fields)
    tasks = _tasks(document["tasks"], allow_empty=False)
    completed_tasks = _tasks(document["completedTasks"], allow_empty=True)
    mode = cast(Mode, _choice(document["mode"], ("exam", "practice")))
    if (mode == "exam" and tasks != (1, 2, 3)) or (mode == "practice" and len(tasks) != 1):
        raise _invalid()
    if not set(completed_tasks).issubset(tasks):
        raise _invalid()
    current_task = _task(document["currentTask"])
    if current_task not in tasks:
        raise _invalid()
    started_at, started = _timestamp(document["startedAt"])
    return (
        ProgressRun(
            id=_string(document["id"], minimum=1, maximum=120),
            variant_id=_string(document["variantId"], minimum=1, maximum=80),
            variant_label=_string(document["variantLabel"], minimum=1, maximum=160),
            mode=mode,
            tasks=tasks,
            completed_tasks=completed_tasks,
            current_task=current_task,
            phase=cast(Phase, _choice(document["phase"], ("idle", "prep", "answer"))),
            fast_mode=_boolean(document["fastMode"]),
            started_at=started_at,
        ),
        started,
    )


def _parse_active_run(value: object) -> ProgressRun:
    run, _ = _parse_run_fields(value, RUN_FIELDS)
    return run


def _parse_completed_run(value: object) -> CompletedProgressRun:
    run, started = _parse_run_fields(value, COMPLETED_FIELDS)
    document = cast(dict[str, object], value)
    status = cast(RunStatus, _choice(document["status"], ("completed", "interrupted")))
    completed_at, completed = _timestamp(document["completedAt"])
    if completed < started or (status == "completed" and run.completed_tasks != run.tasks):
        raise _invalid()
    return CompletedProgressRun(
        **run.__dict__,
        status=status,
        completed_at=completed_at,
        recordings_count=_integer(document["recordingsCount"], minimum=0, maximum=100),
    )


def _parse_settings(value: object) -> ProgressSettings:
    document = _object(value, SETTINGS_FIELDS)
    last_variant = document["lastVariant"]
    if last_variant is not None:
        last_variant = _string(last_variant, minimum=1, maximum=80)
    return ProgressSettings(last_variant, _boolean(document["fastMode"]))


def _parse_v2(value: object) -> ProgressDocument:
    document = _object(value, ROOT_FIELDS)
    if type(document["version"]) is not int or document["version"] != 2:
        raise _invalid()
    updated_at, _ = _timestamp(document["updatedAt"])
    raw_runs = document["runs"]
    if type(raw_runs) is not list or len(raw_runs) > 100:
        raise _invalid()
    runs = tuple(_parse_completed_run(item) for item in raw_runs)
    if len({run.id for run in runs}) != len(runs):
        raise _invalid()
    raw_active_run = document["activeRun"]
    active_run = None if raw_active_run is None else _parse_active_run(raw_active_run)
    return ProgressDocument(updated_at, _parse_settings(document["settings"]), runs, active_run)


def _known_fields(value: object, fields: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict:
        raise _invalid()
    return {name: value[name] for name in fields if name in value}


def _legacy_timestamp(value: object) -> str:
    try:
        timestamp, _ = _timestamp(value)
    except ProgressValidationError:
        return EPOCH
    return timestamp


def _legacy_settings(value: object) -> dict[str, object]:
    if type(value) is not dict:
        value = {}
    last_variant = value.get("lastVariant")
    if type(last_variant) is not str or not 1 <= len(last_variant) <= 80:
        last_variant = None
    fast_mode = value.get("fastMode")
    if type(fast_mode) is not bool:
        fast_mode = False
    return {"lastVariant": last_variant, "fastMode": fast_mode}


def _migrate_v1(document: dict[str, object]) -> ProgressDocument:
    raw_runs = document.get("runs", [])
    if type(raw_runs) is not list:
        raise _invalid()
    if len(raw_runs) > 200:
        raise ProgressValidationError("history_too_large")
    runs: list[dict[str, object]] = []
    seen: set[str] = set()
    for value in raw_runs:
        try:
            migrated = _completed_run_to_dict(_parse_completed_run(_known_fields(value, COMPLETED_FIELDS)))
        except ProgressValidationError:
            continue
        run_id = cast(str, migrated["id"])
        if run_id in seen:
            continue
        seen.add(run_id)
        runs.append(migrated)
        if len(runs) == 100:
            break
    active_run = None
    if document.get("activeRun") is not None:
        try:
            active_run = _run_to_dict(_parse_active_run(_known_fields(document["activeRun"], RUN_FIELDS)))
        except ProgressValidationError:
            pass
    migrated_document = {
        "version": 2,
        "updatedAt": _legacy_timestamp(document.get("updatedAt", EPOCH)),
        "settings": _legacy_settings(document.get("settings")),
        "runs": runs,
        "activeRun": active_run,
    }
    return _parse_v2(migrated_document)


def normalize_progress(document: object) -> ProgressDocument:
    if type(document) is not dict:
        raise _invalid()
    version = document.get("version")
    if type(version) is not int:
        raise _invalid()
    if version == 1:
        return _migrate_v1(document)
    if version == 2:
        return _parse_v2(document)
    raise _invalid()


def _run_to_dict(run: ProgressRun) -> dict[str, object]:
    return {
        "id": run.id,
        "variantId": run.variant_id,
        "variantLabel": run.variant_label,
        "mode": run.mode,
        "tasks": list(run.tasks),
        "completedTasks": list(run.completed_tasks),
        "currentTask": run.current_task,
        "phase": run.phase,
        "fastMode": run.fast_mode,
        "startedAt": run.started_at,
    }


def _completed_run_to_dict(run: CompletedProgressRun) -> dict[str, object]:
    return {
        **_run_to_dict(run),
        "status": run.status,
        "completedAt": run.completed_at,
        "recordingsCount": run.recordings_count,
    }


def progress_to_dict(document: ProgressDocument) -> dict[str, object]:
    return {
        "version": document.version,
        "updatedAt": document.updated_at,
        "settings": {
            "lastVariant": document.settings.last_variant,
            "fastMode": document.settings.fast_mode,
        },
        "runs": [_completed_run_to_dict(run) for run in document.runs],
        "activeRun": _run_to_dict(document.active_run) if document.active_run is not None else None,
    }


def validate_progress(document: object) -> None:
    normalize_progress(document)
