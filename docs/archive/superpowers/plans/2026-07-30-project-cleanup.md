# План чистки проекта

> **Для агентов:** ОБЯЗАТЕЛЬНЫЙ СУБ-СКИЛЛ: используйте superpowers:subagent-driven-development
> (рекомендуется) или superpowers:executing-plans для выполнения плана задача за задачей.
> Шаги размечены чекбоксами (`- [ ]`) для отслеживания.

**Цель:** убрать из проекта неиспользуемые подсистемы (PostgreSQL, транскрипция, legacy runtime) и
заменить эмуляцию `BaseHTTPRequestHandler` нативным транспортом FastAPI.

**Архитектура:** работа идёт тремя фазами. Фаза 1 — удаления, они сокращают площадь последующей
переделки. Фаза 2 — снятие шима: действия контроллеров становятся обычными функциями, возвращающими
данные, а маршруты FastAPI превращают результат в ответ. Фаза 3 — точечные правки интерфейса,
эксплуатации и репозитория.

**Стек:** Python 3.12, FastAPI, Starlette, Pydantic v2, Alembic, SQLite, unittest, Playwright,
нативные ES-модули без сборки.

**Спека:** [docs/superpowers/specs/2026-07-30-project-cleanup-design.md](../specs/2026-07-30-project-cleanup-design.md)

## Глобальные ограничения

- Python 3.12+, ruff `line-length = 120`, двойные кавычки. ESLint покрывает `frontend/js`, `tests-js`, `tests-e2e`.
- Сообщения коммитов — на русском, короткий глагол в повелительной форме.
- Пользовательские строки и документация — на русском.
- Публичный HTTP-контракт не меняется, кроме двух намеренных исключений: поля `database` и `errors`
  уходят из `/api/health` (задача 16), поля `transcript_status` и `transcript_text` — из записей в
  ответах преподавателю (задача 5).
- SQLite-baseline миграций 1–7 в `sqlite_migrations.py` заморожен и не редактируется.
- Опубликованные Alembic-ревизии не редактируются. Единственное исключение — механический перенос
  литерала `POSTGRES_SCHEMA` в задаче 2, разрешённый ADR 0004.
- `domain/` не импортирует `trainer.api`, `fastapi`, `boto3`, `openai`, `smtplib`, `os`.
  `infrastructure/` не импортирует `trainer.api`. Проверяется `tests/unit/test_architecture_boundaries.py`.
- Порог `fail_under = 70` в `pyproject.toml` понижать запрещено.
- `make check` должен быть зелёным перед каждым коммитом, завершающим задачу.
- Сам файл этого плана в задаче 22 перестаёт отслеживаться Git — это ожидаемо, коммитить его повторно
  не нужно.

---

## Фаза 1. Удаления

### Задача 1: Удалить legacy runtime

**Файлы:**
- Удалить: `legacy/` целиком (`server.py`, `README.md`, `__init__.py`, `tests/__init__.py`, `tests/test_server.py`)
- Изменить: `tests/unit/test_package_layout.py:33-38`
- Изменить: `README.md` (последняя строка списка «Для разработчика и владельца проекта»)
- Изменить: `docs/decisions/0001-fastapi-runtime.md:3`

**Интерфейсы:**
- Использует: ничего от предыдущих задач.
- Даёт: отсутствие каталога `legacy/` — задача 15 полагается на это при удалении `transport.py`.

- [ ] **Шаг 1: Переписать тест на отсутствие legacy**

В `tests/unit/test_package_layout.py` замените метод `test_legacy_server_is_outside_the_main_runtime_path`:

```python
    def test_legacy_runtime_is_removed(self):
        root = Path(__file__).resolve().parents[2]

        self.assertFalse((root / "server.py").exists())
        self.assertFalse((root / "legacy").exists())
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.unit.test_package_layout.PackageLayoutTest.test_legacy_runtime_is_removed -v
```

Ожидается: FAIL — `AssertionError: True is not false` (каталог `legacy` ещё существует).

- [ ] **Шаг 3: Удалить каталог**

```bash
git rm -r legacy
```

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.unit.test_package_layout.PackageLayoutTest.test_legacy_runtime_is_removed -v
```

Ожидается: PASS.

- [ ] **Шаг 5: Убрать ссылку из README**

В `README.md` удалите строку:

```markdown
- [legacy/README.md](legacy/README.md) — временно сохранённый compatibility runtime, не входящий в основной workflow.
```

Точку с запятой в конце предыдущей строки списка замените на точку.

- [ ] **Шаг 6: Обновить статус ADR 0001**

В `docs/decisions/0001-fastapi-runtime.md` замените строку статуса:

```markdown
**Статус:** Accepted (реализовано 2026-07-30: каталог `legacy/` удалён)
```

Остальной текст решения не трогайте.

- [ ] **Шаг 7: Прогнать полный набор тестов**

```bash
make check
```

Ожидается: зелёный прогон. Если `test_worker_does_not_import_legacy_server` падает — это ожидаемо
только в том случае, если вы уже выполняли задачу 5; иначе он должен проходить.

- [ ] **Шаг 8: Коммит**

```bash
git add -A && git commit -m "Удалить legacy runtime"
```

---

### Задача 2: Освободить миграции от модуля postgres

**Файлы:**
- Изменить: `migrations/versions/20260705_01_initial_postgres.py:1-17`
- Создать: `docs/decisions/0004-sqlite-only-storage.md`
- Изменить: `docs/decisions/0003-database-migration-strategy.md:3`

**Интерфейсы:**
- Использует: ничего.
- Даёт: `migrations/` больше не импортирует `trainer.infrastructure.database.postgres` — задача 3
  полагается на это при удалении модуля.

- [ ] **Шаг 1: Написать падающий тест**

Создайте `tests/unit/test_migration_independence.py`:

```python
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class MigrationIndependenceTest(unittest.TestCase):
    def test_revisions_do_not_import_the_postgres_adapter(self):
        offenders = []
        for path in (ROOT / "migrations").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("database.postgres"):
                    offenders.append(path.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.unit.test_migration_independence -v
```

Ожидается: FAIL — `AssertionError: ['20260705_01_initial_postgres.py'] != []`.

- [ ] **Шаг 3: Извлечь литерал схемы**

Выполните, чтобы получить текст константы без ручного копирования:

```bash
.venv/bin/python -c "from trainer.infrastructure.database.postgres import POSTGRES_SCHEMA; print(POSTGRES_SCHEMA)" > /tmp/postgres_schema.sql && wc -l /tmp/postgres_schema.sql
```

Ожидается: файл с SQL-инструкциями `CREATE TABLE` и `CREATE INDEX`, непустой.

- [ ] **Шаг 4: Перенести литерал в файл ревизии**

Вставьте содержимое `/tmp/postgres_schema.sql` в `migrations/versions/20260705_01_initial_postgres.py`
как модульную константу `_POSTGRES_SCHEMA` внутри тройных кавычек. Замените заголовок файла:

```python
"""Initial PostgreSQL schema for scale deployments."""

from alembic import op

# Схема перенесена сюда из удалённого trainer.infrastructure.database.postgres:
# ревизия опубликована и не может менять поведение, а модуль-источник больше
# не существует. Ветка исполняется только на PostgreSQL, поддержка которого
# снята (ADR 0004), поэтому фактически она мертва и оставлена ради целостности
# цепочки ревизий.
_POSTGRES_SCHEMA = """<тело константы>"""

revision = "20260705_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in _POSTGRES_SCHEMA.split(";"):
        if statement.strip():
            op.execute(statement)
```

Функцию `downgrade()` не трогайте.

- [ ] **Шаг 5: Сверить перенос**

```bash
.venv/bin/python -c "
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location('rev', 'migrations/versions/20260705_01_initial_postgres.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
from trainer.infrastructure.database.postgres import POSTGRES_SCHEMA
print(module._POSTGRES_SCHEMA.strip() == POSTGRES_SCHEMA.strip())
"
```

Ожидается: `True`. Если `False` — перенос неточен, повторите шаг 4.

- [ ] **Шаг 6: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.unit.test_migration_independence -v
```

Ожидается: PASS.

- [ ] **Шаг 7: Проверить, что цепочка миграций цела**

```bash
rm -rf /tmp/plan-task2 && TRAINER_DATA_DIR=/tmp/plan-task2 .venv/bin/alembic upgrade head && TRAINER_DATA_DIR=/tmp/plan-task2 .venv/bin/alembic current
```

Ожидается: `alembic current` печатает актуальный head без ошибок импорта.

- [ ] **Шаг 8: Записать ADR 0004**

Создайте `docs/decisions/0004-sqlite-only-storage.md`:

```markdown
# ADR 0004: SQLite как единственный движок базы данных

**Статус:** Accepted

## Контекст

Проект поддерживал два движка: SQLite по умолчанию и PostgreSQL для развёртывания с `compose.scale.yml`.
Поддержка PostgreSQL реализована трансляцией SQLite-диалекта на лету и требует ручного ведения списка
`IDENTITY_TABLES`: таблица, забытая в этом списке, молча возвращает `None` из `cursor.lastrowid`.
PostgreSQL ни разу не использовался в эксплуатации.

## Решение

SQLite — единственный поддерживаемый движок. Переменная `DATABASE_URL` не читается. Соединение
открывается в режиме WAL.

Требования ADR 0003 о dual-dialect ревизиях и о проверке паритета схем двух СУБД отменяются. Требование
«Alembic — канонический владелец изменений схемы» и заморозка SQLite-baseline 1–7 сохраняются.

Литерал `POSTGRES_SCHEMA` перенесён из удалённого модуля адаптера внутрь ревизии `20260705_01`. Это
единственное разрешённое изменение опубликованной ревизии: оно механическое, поведение сохраняется
байт-в-байт, а затронутая ветка после отказа от PostgreSQL не исполняется.

## Последствия

- Снимается ловушка `IDENTITY_TABLES` при добавлении таблиц.
- Из CI, Docker-образа и compose уходят PostgreSQL-сервис и клиент.
- Горизонтальное масштабирование приложения потребует возврата к внешней СУБД; при текущей нагрузке
  (десятки пользователей) SQLite в режиме WAL закрывает потребность с многократным запасом.
- Резервное копирование выполняется копированием файла базы и каталога аудио.
```

- [ ] **Шаг 9: Обновить статус ADR 0003**

В `docs/decisions/0003-database-migration-strategy.md` замените строку статуса:

```markdown
**Статус:** Superseded by [ADR 0004](0004-sqlite-only-storage.md) в части dual-dialect; правила Alembic и заморозка baseline действуют
```

Остальной текст не трогайте.

- [ ] **Шаг 10: Коммит**

```bash
git add -A && git commit -m "Перенести схему PostgreSQL внутрь начальной ревизии"
```

---

### Задача 3: Удалить адаптер PostgreSQL и включить WAL

**Файлы:**
- Удалить: `src/trainer/infrastructure/database/postgres.py`, `scripts/postgres_smoke.py`, `scripts/postgres_restore_smoke.py`, `compose.scale.yml`
- Изменить: `src/trainer/infrastructure/database/core.py`, `src/trainer/infrastructure/database/migrations.py:28-62`
- Изменить: `src/trainer/main.py:20-27,36-38,124-132`
- Изменить: `scripts/backup.py:20-30,60-70`
- Изменить: `tests/integration/test_migrations.py`, `tests/integration/test_storage_transcription.py`
- Изменить: `requirements.txt`, `Dockerfile:5-12`, `Makefile:55-61`, `.env.example`, `.github/workflows/ci.yml`

**Интерфейсы:**
- Использует: результат задачи 2 (миграции не импортируют `postgres.py`).
- Даёт: `core.connect(path) -> sqlite3.Connection` без ветвления по `DATABASE_URL`;
  `core.INTEGRITY_ERRORS = sqlite3.IntegrityError`. Функции `engine_name()` и `close_connections()`
  отсутствуют — задача 16 полагается на это в `/api/health`.

- [ ] **Шаг 1: Написать падающий тест на WAL**

Добавьте в `tests/integration/test_queries.py`:

```python
    def test_connection_uses_write_ahead_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "trainer.db"
            initialize(root, root / "audio", database_path)
            with connect(database_path) as database:
                mode = database.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")
```

Импорты `tempfile`, `Path`, `connect`, `initialize` в этом файле уже есть; если какого-то нет — добавьте.

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.integration.test_queries -v -k write_ahead
```

Ожидается: FAIL — `'delete' != 'wal'`.

- [ ] **Шаг 3: Переписать core.py**

Замените `src/trainer/infrastructure/database/core.py` целиком:

```python
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from trainer.infrastructure.database.migrations import upgrade_sqlite_database

INTEGRITY_ERRORS = sqlite3.IntegrityError


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    # WAL включаем на каждом соединении: режим журнала хранится в файле базы,
    # но повторная установка дешёвая и снимает зависимость от порядка запуска.
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize(data_dir: Path, audio_dir: Path, database_path: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    upgrade_sqlite_database(database_path)
    with connect(database_path) as database:
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        database.execute("DELETE FROM account_tokens WHERE expires_at <= ?", (int(time.time()),))
        database.execute("DELETE FROM auth_rate_limits WHERE updated_at <= ?", (int(time.time()) - 30 * 86400,))
```

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.integration.test_queries -v -k write_ahead
```

Ожидается: PASS.

- [ ] **Шаг 5: Упростить migrations.py**

В `src/trainer/infrastructure/database/migrations.py` удалите `normalize_database_url`,
`MIGRATION_LOCK_KEY`, `MIGRATION_LOCK_TIMEOUT_MS` и импорты `os`, `create_engine`, `text`,
`OperationalError`. Замените `_config` и `upgrade_database`:

```python
def _config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(database_url: str) -> None:
    command.upgrade(_config(database_url), "head")
```

В `current_revision` замените `create_engine(normalize_database_url(database_url))` на
`create_engine(database_url)` и оставьте импорт `create_engine`.

- [ ] **Шаг 6: Удалить файлы адаптера**

```bash
git rm src/trainer/infrastructure/database/postgres.py scripts/postgres_smoke.py scripts/postgres_restore_smoke.py compose.scale.yml
```

- [ ] **Шаг 7: Убрать PostgreSQL из main.py**

В `src/trainer/main.py` удалите импорт `close_connections, engine_name` из
`trainer.infrastructure.database.core`, вызов `close_connections()` в `lifespan` и упоминание
`engine_name()` в `/api/health`. Временно приведите health к виду:

```python
@app.get("/api/health")
async def health():
    try:
        await run_in_threadpool(_check_database)
    except Exception:
        return JSONResponse({"ok": False, "errors": error_monitor.snapshot()}, status_code=503)
    return {"ok": True, "errors": error_monitor.snapshot()}
```

Поле `errors` убирается в задаче 16.

- [ ] **Шаг 8: Убрать pg_dump из backup.py**

В `scripts/backup.py` удалите ветку с вызовом `pg_dump` и чтение `os.environ.get("DATABASE_URL", "")`.
Оставьте копирование файла SQLite и каталога аудио. Если после этого `os` не используется — удалите импорт.

- [ ] **Шаг 9: Почистить тесты**

В `tests/integration/test_migrations.py` удалите класс PostgreSQL-теста и проверку паритета схем.
Переименуйте `tests/integration/test_storage_transcription.py` в `tests/integration/test_storage.py`
и удалите из него импорт `from trainer.infrastructure.database.postgres import ...` вместе с
использующими его тестами:

```bash
git mv tests/integration/test_storage_transcription.py tests/integration/test_storage.py
```

- [ ] **Шаг 10: Почистить конфигурацию окружения**

- `requirements.txt`: удалить строку `psycopg[binary,pool]==3.3.2`.
- `Dockerfile`: удалить установку репозитория PGDG (строки с `curl`, `gnupg`, `pgdg`,
  `postgresql-client-16`, `pg_dump --version`). Оставить установку `ffmpeg` и `fonts-dejavu-core`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 trainer
```

`curl` остаётся: он нужен `HEALTHCHECK`.

- `Makefile`: в цели `docker-check` удалить строку
  `docker compose -f compose.yml -f compose.scale.yml config --quiet;` и точку с запятой после
  предыдущей строки заменить на её отсутствие.
- `.env.example`: удалить `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, комментарий про
  `compose.scale.yml` и закомментированный `DATABASE_URL`.
- `.github/workflows/ci.yml`: удалить блок `services: postgres`, установку `postgresql-client` и
  проверку `pg_dump --version` из шага «Install system tools», шаг «Test PostgreSQL adapter».

- [ ] **Шаг 11: Прогнать проверки**

```bash
make check
```

Ожидается: зелёный прогон.

```bash
.venv/bin/python -m scripts.sqlite_restore_smoke
```

Ожидается: успешное завершение с кодом 0.

- [ ] **Шаг 12: Коммит**

```bash
git add -A && git commit -m "Удалить поддержку PostgreSQL и включить WAL"
```

---

### Задача 4: Удалить код транскрипции

**Файлы:**
- Удалить: `src/trainer/services/transcription.py`, `src/trainer/infrastructure/transcription.py`, `src/trainer/workers/` целиком, `scripts/transcription_worker.py`, `docs/runbooks/transcription-worker.md`
- Изменить: `src/trainer/api/controllers/recordings.py:12-16,84-90`
- Изменить: `tests/unit/test_package_layout.py:25-31`, `tests/integration/test_storage.py`
- Изменить: `requirements.txt`, `compose.yml:19-29`, `.env.example`, `.github/workflows/ci.yml`

**Интерфейсы:**
- Использует: результат задачи 3 (`test_storage.py` уже переименован).
- Даёт: `recordings` вставляются без колонки `transcript_status` — задача 6 полагается на это перед
  удалением колонок из схемы.

- [ ] **Шаг 1: Написать падающий тест**

Добавьте в `tests/integration/test_api_flows.py` метод в существующий класс сценариев записи:

```python
    def test_recording_row_has_no_transcription_columns(self):
        source = (Path(__file__).resolve().parents[2] / "src/trainer/api/controllers/recordings.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("transcript_status", source)
        self.assertNotIn("enqueue_transcription", source)
```

Если `Path` в файле не импортирован — добавьте `from pathlib import Path`.

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.integration.test_api_flows -v -k transcription_columns
```

Ожидается: FAIL — `'transcript_status' unexpectedly found`.

- [ ] **Шаг 3: Почистить контроллер записей**

В `src/trainer/api/controllers/recordings.py` удалите импорты:

```python
from trainer.services.transcription import enabled as transcription_enabled
from trainer.services.transcription import enqueue as enqueue_transcription
```

Замените вставку записи: уберите колонку `transcript_status` из списка колонок и соответствующее
значение `"pending" if transcription_enabled() else "disabled"` из кортежа параметров, а также блок:

```python
                if transcription_enabled():
                    enqueue_transcription(database, cursor.lastrowid)
```

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.integration.test_api_flows -v -k transcription_columns
```

Ожидается: PASS.

- [ ] **Шаг 5: Удалить модули**

```bash
git rm src/trainer/services/transcription.py src/trainer/infrastructure/transcription.py scripts/transcription_worker.py docs/runbooks/transcription-worker.md
git rm -r src/trainer/workers
```

- [ ] **Шаг 6: Убрать тест, импортирующий воркер**

В `tests/unit/test_package_layout.py` удалите метод `test_worker_does_not_import_legacy_server` целиком
и неиспользуемый после этого импорт `sys`, если он больше нигде не нужен.

- [ ] **Шаг 7: Почистить тесты хранилища и конфигурацию**

В `tests/integration/test_storage.py` удалите импорт `from trainer.services.transcription import ...`
и все тесты очереди расшифровки (`claim`, `complete`, `fail`, `enqueue`).

- `requirements.txt`: удалить `openai==2.44.0`.
- `compose.yml`: удалить сервис `transcription-worker` целиком.
- `.env.example`: удалить `TRAINER_TRANSCRIPTION_ENABLED`, `OPENAI_API_KEY`,
  `OPENAI_TRANSCRIPTION_MODEL`, `TRAINER_TRANSCRIPTION_LANGUAGE`.
- `.github/workflows/ci.yml`: в шаге «Test operational commands» удалить строки создания `worker_data`
  и запуск `trainer.workers.transcription --once`; оставить `python -m scripts.sqlite_restore_smoke`.

- [ ] **Шаг 8: Прогнать проверки**

```bash
make check
```

Ожидается: зелёный прогон.

- [ ] **Шаг 9: Коммит**

```bash
git add -A && git commit -m "Удалить стек транскрипции аудиозаписей"
```

---

### Задача 5: Убрать расшифровки из ответов и интерфейса

**Файлы:**
- Изменить: `src/trainer/infrastructure/database/queries/combined.py` (выборка записей для преподавателя)
- Изменить: `frontend/js/account/account-view.js:47,57-68`
- Изменить: `frontend/styles/base.css:346-347`
- Изменить: `tests-js/unit/views.test.js`

**Интерфейсы:**
- Использует: результат задачи 4.
- Даёт: записи в ответах преподавателю содержат только `id`, `label`, `url`, `taskNumber` и длительность —
  задача 6 полагается на то, что колонки больше не читаются.

- [ ] **Шаг 1: Написать падающий JS-тест**

В `tests-js/unit/views.test.js` добавьте:

```javascript
test("submission markup does not render transcripts", () => {
  const markup = submissionMarkup({
    id: 1,
    title: "Работа",
    status: "submitted",
    attempt: 1,
    recordings: [{ id: 7, label: "Задание 1", url: "/api/recordings/7", transcript_status: "completed", transcript_text: "текст" }],
  });
  assert.ok(!markup.includes("Расшифровка"));
  assert.ok(!markup.includes("текст"));
});
```

Имя импортируемой функции возьмите из существующих тестов этого файла — там уже импортируется
рендер работ из `account-view.js`.

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
node --test tests-js/unit/views.test.js
```

Ожидается: FAIL — разметка содержит «Расшифровка».

- [ ] **Шаг 3: Удалить разметку расшифровки**

В `frontend/js/account/account-view.js` удалите функцию `transcriptMarkup` целиком и вызов
`${transcriptMarkup(recording)}` из шаблона записи.

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
node --test tests-js/unit/views.test.js
```

Ожидается: PASS.

- [ ] **Шаг 5: Убрать стили и колонки из выборки**

В `frontend/styles/base.css` удалите правила `.recording-transcript`, `.recording-transcript summary`
и `.transcript-status`.

В `src/trainer/infrastructure/database/queries/combined.py` найдите SQL, выбирающий записи для
преподавателя, и удалите из списка колонок `recordings.transcript_status`, `recordings.transcript_text`
и любые другие `transcript_*`, а также их перенос в словарь ответа.

- [ ] **Шаг 6: Прогнать проверки**

```bash
make check
```

Ожидается: зелёный прогон. Интеграционные тесты, ожидающие поля расшифровки в ответе, поправьте —
это одно из двух намеренных изменений контракта.

- [ ] **Шаг 7: Коммит**

```bash
git add -A && git commit -m "Убрать расшифровки из ответов и кабинета"
```

---

### Задача 6: Удалить схему транскрипции миграцией

**Файлы:**
- Создать: `migrations/versions/20260730_05_drop_transcription.py`
- Изменить: `tests/integration/test_migrations.py`

**Интерфейсы:**
- Использует: результаты задач 4 и 5 (код больше не обращается к таблице и колонкам).
- Даёт: head-ревизия `20260730_05`.

- [ ] **Шаг 1: Написать падающий тест**

Добавьте в `tests/integration/test_migrations.py`:

```python
    def test_head_removes_transcription_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer.db"
            upgrade_sqlite_database(path)
            with closing(sqlite3.connect(path)) as database:
                tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                columns = {row[1] for row in database.execute("PRAGMA table_info(recordings)")}
        self.assertNotIn("transcription_jobs", tables)
        self.assertFalse({"transcript_status", "transcript_text", "transcript_error", "transcribed_at"} & columns)
```

Импорты `tempfile`, `Path`, `closing`, `sqlite3`, `upgrade_sqlite_database` в этом файле уже есть.

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.integration.test_migrations -v -k transcription_schema
```

Ожидается: FAIL — `'transcription_jobs' unexpectedly found in tables`.

- [ ] **Шаг 3: Определить текущий head**

```bash
.venv/bin/alembic heads
```

Запишите идентификатор — он станет `down_revision` новой ревизии.

- [ ] **Шаг 4: Написать ревизию**

Создайте `migrations/versions/20260730_05_drop_transcription.py`:

```python
"""Drop transcription queue and recording transcript columns."""

import sqlalchemy as sa
from alembic import op

revision = "20260730_05"
down_revision = "<идентификатор из шага 3>"
branch_labels = None
depends_on = None

TRANSCRIPT_COLUMNS = ("transcript_status", "transcript_text", "transcript_error", "transcribed_at")


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS transcription_jobs_queue_idx")
    op.execute("DROP TABLE IF EXISTS transcription_jobs")
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("recordings")}
    with op.batch_alter_table("recordings") as batch:
        for name in TRANSCRIPT_COLUMNS:
            if name in existing:
                batch.drop_column(name)


def downgrade() -> None:
    with op.batch_alter_table("recordings") as batch:
        batch.add_column(sa.Column("transcript_status", sa.Text(), nullable=False, server_default="disabled"))
        batch.add_column(sa.Column("transcript_text", sa.Text()))
        batch.add_column(sa.Column("transcript_error", sa.Text()))
        batch.add_column(sa.Column("transcribed_at", sa.Integer()))
    op.create_table(
        "transcription_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recording_id", sa.Integer(), sa.ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
    )
    op.create_index("transcription_jobs_queue_idx", "transcription_jobs", ["status", "available_at", "id"])
```

Точные типы и ограничения колонок сверьте с `migration_005_transcriptions` в
`src/trainer/infrastructure/database/sqlite_migrations.py:157-185` — `downgrade` должен восстанавливать
их в исходном виде.

- [ ] **Шаг 5: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.integration.test_migrations -v -k transcription_schema
```

Ожидается: PASS.

- [ ] **Шаг 6: Проверить обратимость**

```bash
rm -rf /tmp/plan-task6 && mkdir -p /tmp/plan-task6
TRAINER_DATA_DIR=/tmp/plan-task6 .venv/bin/alembic upgrade head
TRAINER_DATA_DIR=/tmp/plan-task6 .venv/bin/alembic downgrade -1
TRAINER_DATA_DIR=/tmp/plan-task6 .venv/bin/alembic upgrade head
```

Ожидается: все три команды завершаются без ошибок.

- [ ] **Шаг 7: Прогнать проверки**

```bash
make check && make test-e2e
```

Ожидается: зелёный прогон обоих.

- [ ] **Шаг 8: Коммит**

```bash
git add -A && git commit -m "Удалить схему транскрипции новой ревизией"
```

---

## Фаза 2. Снятие шима

### Задача 7: Ввести ApiError, ActionResult и RequestContext

**Файлы:**
- Изменить: `src/trainer/api/errors.py`
- Создать: `src/trainer/api/results.py`
- Изменить: `src/trainer/main.py`
- Создать: `tests/integration/test_error_contract.py`

**Интерфейсы:**
- Использует: ничего от фазы 1, кроме зелёного состояния.
- Даёт:
  - `ApiError(code: str, message: str, status: int = 400)` — исключение с атрибутами `code`,
    `message`, `status`;
  - `ActionResult(payload: dict, status: int = 200, session_token: str | None = None,
    clear_session: bool = False, headers: dict[str, str] | None = None)`;
  - `FileResult(key: str, mime_type: str, size_bytes: int)`;
  - `RequestContext(client_ip: str, user_agent: str)`.
  Задачи 8–14 используют эти типы.

- [ ] **Шаг 1: Написать падающий тест**

Создайте `tests/integration/test_error_contract.py`:

```python
from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trainer.api.errors import ApiError, api_error_handler


class ErrorContractTest(unittest.TestCase):
    def client(self) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(ApiError, api_error_handler)

        @app.get("/boom")
        async def boom():
            raise ApiError("teacher_not_allowed", "Роль преподавателя недоступна", 403)

        return TestClient(app, raise_server_exceptions=False)

    def test_handler_keeps_error_payload_shape(self):
        response = self.client().get("/boom")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "teacher_not_allowed")
        self.assertEqual(response.json()["message"], "Роль преподавателя недоступна")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.integration.test_error_contract -v
```

Ожидается: FAIL — `ImportError: cannot import name 'ApiError'`.

- [ ] **Шаг 3: Добавить ApiError и обработчик**

Допишите в конец `src/trainer/api/errors.py`:

```python
import logging

from fastapi.responses import JSONResponse

from trainer.infrastructure.observability import log_event


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


async def api_error_handler(request, error: ApiError) -> JSONResponse:
    log_event(
        logging.getLogger("trainer.api"),
        logging.WARNING if error.status < 500 else logging.ERROR,
        "api_error",
        error.message,
        code=error.code,
        status=error.status,
        path=request.url.path,
    )
    return JSONResponse(error_payload(error.code, error.message), status_code=error.status)
```

Импорты перенесите в начало файла к остальным.

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.integration.test_error_contract -v
```

Ожидается: PASS.

- [ ] **Шаг 5: Добавить типы результата действия**

Создайте `src/trainer/api/results.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestContext:
    """Данные запроса, нужные действиям для аудита и писем."""

    client_ip: str
    user_agent: str


@dataclass
class ActionResult:
    """Результат действия: тело ответа и то, что маршрут должен добавить к нему."""

    payload: dict
    status: int = 200
    session_token: str | None = None
    clear_session: bool = False
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FileResult:
    """Ссылка на файл в хранилище; чтение выполняет маршрут."""

    key: str
    mime_type: str
    size_bytes: int
```

- [ ] **Шаг 6: Зарегистрировать обработчик в приложении**

В `src/trainer/main.py` добавьте импорт `ApiError, api_error_handler` из `trainer.api.errors` и строку
после создания `app`:

```python
app.add_exception_handler(ApiError, api_error_handler)
```

- [ ] **Шаг 7: Прогнать проверки и закоммитить**

```bash
make check
git add -A && git commit -m "Добавить ApiError и типы результата действия"
```

---

### Задача 8: Перевести проверку роли на зависимости FastAPI

**Файлы:**
- Изменить: `src/trainer/api/dependencies.py`
- Создать: `src/trainer/api/cookies.py`
- Создать: `tests/integration/test_role_dependencies.py`

**Интерфейсы:**
- Использует: `ApiError` из задачи 7.
- Даёт:
  - `current_user_or_none(request) -> dict | None`;
  - `require_student(request) -> dict` и `require_teacher(request) -> dict` — бросают `ApiError`;
  - `request_context(request) -> RequestContext`;
  - `session_cookie(token: str) -> str` и `cleared_session_cookie() -> str` в `api/cookies.py`.
  Задачи 10–14 используют эти зависимости в маршрутах.

- [ ] **Шаг 1: Написать падающий тест**

Создайте `tests/integration/test_role_dependencies.py`:

```python
from __future__ import annotations

import unittest

from trainer.api.dependencies import require_teacher
from trainer.api.errors import ApiError


class FakeRequest:
    def __init__(self, cookie: str = ""):
        self.headers = {"Cookie": cookie, "User-Agent": "test"}
        self.client = type("Client", (), {"host": "127.0.0.1"})()


class RoleDependencyTest(unittest.TestCase):
    def test_missing_session_raises_authentication_required(self):
        with self.assertRaises(ApiError) as raised:
            require_teacher(FakeRequest())

        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.code, "authentication_required")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.integration.test_role_dependencies -v
```

Ожидается: FAIL — `ImportError: cannot import name 'require_teacher'`.

- [ ] **Шаг 3: Написать зависимости**

Добавьте в `src/trainer/api/dependencies.py` функции модульного уровня (класс
`ApiDependenciesMixin` пока оставьте — он уходит в задаче 15):

```python
def session_token(request) -> str | None:
    cookie = SimpleCookie(request.headers.get("Cookie", ""))
    morsel = cookie.get("trainer_session")
    return morsel.value if morsel else None


def request_context(request) -> RequestContext:
    return RequestContext(
        client_ip=request.client.host if request.client else "",
        user_agent=request.headers.get("User-Agent", ""),
    )


def current_user_or_none(request) -> dict | None:
    return account_services.current_user(connect, session_token(request))


def _require_role(request, role: str) -> dict:
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


def require_student(request) -> dict:
    return _require_role(request, "student")


def require_teacher(request) -> dict:
    return _require_role(request, "teacher")


def require_authenticated(request) -> dict:
    user = current_user_or_none(request)
    if not user:
        raise ApiError("authentication_required", "Authentication required", 401)
    return user
```

Добавьте импорты `ApiError`, `default_error_code` из `trainer.api.errors` и `RequestContext` из
`trainer.api.results`.

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.integration.test_role_dependencies -v
```

Ожидается: PASS.

- [ ] **Шаг 5: Вынести cookie сессии**

Создайте `src/trainer/api/cookies.py`:

```python
from __future__ import annotations

import os

from trainer.api.runtime import SESSION_DAYS


def session_cookie(token: str) -> str:
    cookie = f"trainer_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"
    if os.environ.get("TRAINER_SECURE_COOKIE") == "1":
        cookie += "; Secure"
    return cookie


def cleared_session_cookie() -> str:
    return "trainer_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
```

Значения скопированы из `ApiTransportMixin.send_json` без изменений — формат cookie входит в
неизменяемую часть контракта.

- [ ] **Шаг 6: Прогнать проверки и закоммитить**

```bash
make check
git add -A && git commit -m "Перевести проверку роли на зависимости FastAPI"
```

---

### Задача 9: Перенести same-origin и лимит тела в middleware

**Файлы:**
- Изменить: `src/trainer/main.py:50-66`
- Создать: `tests/integration/test_request_guards.py`

**Интерфейсы:**
- Использует: `ApiError` из задачи 7.
- Даёт: POST/PUT/DELETE без валидного origin отвергаются до маршрута с кодом `invalid_origin` и
  статусом 403; тело сверх лимита — с кодом `request_too_large` и статусом 413. Задача 15 полагается
  на это при удалении `invoke`.

- [ ] **Шаг 1: Написать падающий тест**

Создайте `tests/integration/test_request_guards.py`:

```python
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from trainer.main import app


class RequestGuardTest(unittest.TestCase):
    def test_cross_origin_post_is_rejected_before_the_route(self):
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "x"},
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "invalid_origin")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает или проходит по неверной причине**

```bash
.venv/bin/python -m unittest tests.integration.test_request_guards -v
```

Сейчас тест может пройти: проверку делает `invoke`. Это нормально — он фиксирует поведение, которое
должно сохраниться после переноса. Зафиксируйте текущий результат и переходите к шагу 3.

- [ ] **Шаг 3: Добавить middleware**

В `src/trainer/main.py` добавьте после `reject_oversized_json`:

```python
@app.middleware("http")
async def reject_cross_origin_writes(request, call_next):
    if request.method in {"POST", "PUT", "DELETE"} and not request_has_same_origin(
        request.headers.get("Host"),
        request.headers.get("Origin"),
        request.headers.get("Referer"),
        request.headers.get("Sec-Fetch-Site"),
    ):
        return JSONResponse(error_payload("invalid_origin", "Invalid request origin"), status_code=403)
    return await call_next(request)
```

Добавьте импорт `from trainer.api.security import request_has_same_origin`.

- [ ] **Шаг 4: Расширить лимит тела на загрузки**

В том же файле замените `reject_oversized_json` так, чтобы лимит выбирался по пути, а не по имени
действия:

```python
AUDIO_UPLOAD_PATHS = re.compile(r"^/api/(submissions/\d+/recordings|materials/\d+/assets)$")


@app.middleware("http")
async def reject_oversized_body(request, call_next):
    if request.method in BODY_METHODS:
        limit = MAX_AUDIO_BODY if AUDIO_UPLOAD_PATHS.match(request.url.path) else MAX_BODY
        raw_length = request.headers.get("content-length", "")
        if raw_length.isdigit() and int(raw_length) > limit:
            return JSONResponse(
                error_payload("request_too_large", "Request body is too large"),
                status_code=413,
            )
    return await call_next(request)
```

Добавьте импорт `MAX_AUDIO_BODY` из `trainer.api.runtime`. Комментарий про chunked-запросы из
исходной функции сохраните.

- [ ] **Шаг 5: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.integration.test_request_guards -v && make check
```

Ожидается: PASS и зелёный `make check`.

- [ ] **Шаг 6: Коммит**

```bash
git add -A && git commit -m "Перенести проверку origin и лимит тела в middleware"
```

---

### Правила перевода действия (обязательны для задач 10–14)

Эти правила — часть требований каждой из задач 10–14. Применяйте их построчно; сообщения об ошибках,
коды и статусы переносите дословно.

- `self.read_json()` — удалить: провалидированный payload приходит аргументом функции.
- `self.send_json(data)` → `return ActionResult(data)`.
- `self.send_json(data, HTTPStatus.CREATED)` → `return ActionResult(data, status=201)`.
- `self.send_json(data, token=token)` → `return ActionResult(data, session_token=token)`.
- `self.send_json(data, clear_cookie=True)` → `return ActionResult(data, clear_session=True)`.
- `self.send_json(data, extra_headers={...})` → `return ActionResult(data, headers={...})`.
- `self.send_error_json(status, message, code)` →
  `raise ApiError(code or default_error_code(status), message, int(status))`.
- `self.require_role("student")` и следующий за ним `if not user: return` — удалить: пользователь
  приходит аргументом из зависимости маршрута.
- `self.current_user()` → аргумент `user`.
- `self.audit(database, action, ...)` →
  `account_services.audit(database, action, client_ip=context.client_ip, user_agent=context.user_agent, ...)`.
- `self.send_account_link(kind, email, token)` →
  `account_services.send_account_link(connect, DATA_DIR, kind, email, token, public_url=account_public_url(), client_ip=context.client_ip, user_agent=context.user_agent)`.
- `self.send_bytes(data, content_type, filename)` → функция возвращает
  `tuple[bytes, str, str]`, заголовки ставит маршрут.
- `parse_qs(urlparse(self.path).query)` → параметры объявляются аргументами маршрута FastAPI и
  передаются в функцию словарём.
- `self.wfile.write(...)` для файлов → функция возвращает `FileResult`, чтение выполняет маршрут.

Образец преобразования одного действия:

```python
# Было
class AuthControllerMixin:
    def auth_login(self) -> None:
        payload = self.read_json()
        if payload is None:
            return
        ...
        self.send_json({"user": user_payload}, token=token)

# Стало
def auth_login(payload: LoginPayload, context: RequestContext) -> ActionResult:
    ...
    return ActionResult({"user": user_payload}, session_token=token)
```

Образец маршрута:

```python
@router.post("/auth/login")
async def login(payload: LoginPayload, request: Request):
    result = await run_in_threadpool(actions.auth_login, payload, request_context(request))
    return respond(result)


@router.get("/account/audit")
async def account_audit(user: dict = Depends(require_authenticated)):
    return respond(await run_in_threadpool(actions.account_audit, user))
```

---

### Задача 10: Перевести действия аутентификации

**Файлы:**
- Изменить: `src/trainer/api/controllers/auth.py` целиком
- Изменить: `src/trainer/api/routes/accounts.py` целиком

**Интерфейсы:**
- Использует: `ActionResult`, `RequestContext`, `ApiError` (задача 7); `require_authenticated`,
  `request_context`, `current_user_or_none`, `session_cookie`, `cleared_session_cookie` (задача 8).
- Даёт: функции модуля `trainer.api.controllers.auth`:
  - `auth_register(payload: RegisterPayload, context: RequestContext) -> ActionResult`
  - `auth_login(payload: LoginPayload, context: RequestContext) -> ActionResult`
  - `auth_logout(token: str | None, context: RequestContext) -> ActionResult`
  - `auth_me(user: dict | None) -> ActionResult`
  - `email_verification_request(user: dict, context: RequestContext) -> ActionResult`
  - `email_verification_confirm(payload, context) -> ActionResult`
  - `password_reset_request(payload, context) -> ActionResult`
  - `password_reset_confirm(payload, context) -> ActionResult`
  - `account_audit(user: dict) -> ActionResult`
  - `account_delete(payload, user: dict, context: RequestContext) -> ActionResult`

- [ ] **Шаг 1: Зафиксировать текущий контракт**

```bash
.venv/bin/python -m unittest tests.integration.test_accounts -v
```

Ожидается: PASS. Этот прогон — эталон: после перевода те же тесты должны проходить без правок
ожидаемых ответов.

- [ ] **Шаг 2: Написать общий формирователь ответа**

В `src/trainer/api/routes/__init__.py`:

```python
from fastapi.responses import JSONResponse

from trainer.api.cookies import cleared_session_cookie, session_cookie
from trainer.api.results import ActionResult


def respond(result: ActionResult) -> JSONResponse:
    response = JSONResponse(result.payload, status_code=result.status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    for name, value in result.headers.items():
        response.headers[name] = value
    if result.session_token:
        response.headers["Set-Cookie"] = session_cookie(result.session_token)
    elif result.clear_session:
        response.headers["Set-Cookie"] = cleared_session_cookie()
    return response
```

Заголовки `Cache-Control: no-store` и `X-Content-Type-Options: nosniff` скопированы из
`ApiTransportMixin.send_json`: они входят в неизменяемую часть контракта.

- [ ] **Шаг 3: Переписать модуль действий и маршруты**

Превратите `AuthControllerMixin` в модуль функций, применяя раздел «Правила перевода действия».
Маршруты в `src/trainer/api/routes/accounts.py` перепишите по образцу из того же раздела.

Соответствие зависимостей: `auth_register`, `auth_login`, `email_verification_confirm`,
`password_reset_request`, `password_reset_confirm` — без зависимости (гостевые);
`auth_logout` — `session_token`; `auth_me` — `current_user_or_none`;
`email_verification_request`, `account_audit`, `account_delete` — `require_authenticated`.

- [ ] **Шаг 4: Прогнать эталонные тесты**

```bash
.venv/bin/python -m unittest tests.integration.test_accounts -v
```

Ожидается: PASS без изменения ожидаемых ответов. Любое расхождение — сломанный контракт, чините код,
а не тест.

- [ ] **Шаг 5: Коммит**

```bash
git add -A && git commit -m "Перевести действия аутентификации на функции"
```

---

### Задача 11: Перевести действия групп и прогресса

**Файлы:**
- Изменить: `src/trainer/api/controllers/groups.py`, `src/trainer/api/routes/groups.py`

**Интерфейсы:**
- Использует: `respond` (задача 10), зависимости задачи 8.
- Даёт: `progress_get(user)`, `progress_put(payload, user)`, `teacher_group_create(payload, user, context)`,
  `group_join(payload, user, context)`, `student_groups(user)`, `teacher_dashboard(user)` — все
  возвращают `ActionResult`.

- [ ] **Шаг 1: Зафиксировать эталон**

```bash
.venv/bin/python -m unittest tests.integration.test_api_flows -v
```

Ожидается: PASS.

- [ ] **Шаг 2: Перевести модуль и маршруты**

Применяйте раздел «Правила перевода действия» и образец маршрута оттуда же. Соответствие
зависимостей: `progress_get`, `progress_put`, `student_groups`, `group_join` —
`Depends(require_student)`; `teacher_group_create`, `teacher_dashboard` — `Depends(require_teacher)`.

- [ ] **Шаг 3: Импортировать `respond` из `trainer.api.routes`**

Не дублируйте формирователь ответа — он один на все маршруты.

- [ ] **Шаг 4: Прогнать тесты**

```bash
.venv/bin/python -m unittest tests.integration.test_api_flows -v
```

Ожидается: PASS без правки ожидаемых ответов.

- [ ] **Шаг 5: Коммит**

```bash
git add -A && git commit -m "Перевести действия групп и прогресса на функции"
```

---

### Задача 12: Перевести действия работ и экспорта

**Файлы:**
- Изменить: `src/trainer/api/controllers/work.py`, `src/trainer/api/routes/work.py`

**Интерфейсы:**
- Использует: `respond`, `FileResult` (задача 7), зависимости задачи 8.
- Даёт: `student_assignments(user)`, `teacher_assignments(user)`,
  `teacher_assignment_create(payload, user, context)`, `teacher_assignment_update(assignment_id, payload, user, context)`,
  `teacher_assignment_resend(assignment_id, user, context)`, `submission_create(assignment_id, payload, user, context)`,
  `teacher_submissions(query, user)`, `submission_history(submission_id, user)`,
  `review_submission(submission_id, payload, user, context)` → `ActionResult`;
  `teacher_export(fmt: str, query: dict, user) -> tuple[bytes, str, str]` — данные, MIME-тип, имя файла;
  `assignment_asset_get(asset_id, user) -> FileResult`.

- [ ] **Шаг 1: Зафиксировать эталон**

```bash
.venv/bin/python -m unittest tests.integration.test_api_flows tests.integration.test_assignment_assets -v
```

Ожидается: PASS.

- [ ] **Шаг 2: Перевести модуль по разделу «Правила перевода действия»**

Все действия, кроме `assignment_asset_get`, используют `Depends(require_teacher)`, кроме
`student_assignments` и `submission_create` — они `Depends(require_student)`;
`assignment_asset_get` — `Depends(require_authenticated)`.

Для действий, читавших query-параметры через `parse_qs(urlparse(self.path).query)`, параметры
объявляются аргументами маршрута FastAPI и передаются в функцию явным словарём. Пример для
`teacher_submissions`:

```python
@router.get("/teacher/submissions")
async def teacher_submissions(
    request: Request,
    group: str | None = None,
    student: str | None = None,
    status: str | None = None,
    user: dict = Depends(require_teacher),
):
    query = {"group": group, "student": student, "status": status}
    return respond(await run_in_threadpool(actions.teacher_submissions, query, user))
```

- [ ] **Шаг 3: Перевести экспорт**

`self.send_bytes(data, content_type, filename)` заменяется возвратом кортежа и формированием ответа
в маршруте:

```python
@router.get("/teacher/export.csv")
async def export_csv(request: Request, user: dict = Depends(require_teacher)):
    data, content_type, filename = await run_in_threadpool(actions.teacher_export, "csv", dict(request.query_params), user)
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )
```

Маршрут `export.pdf` — тот же код с `"pdf"` вместо `"csv"`.

- [ ] **Шаг 4: Отдать snapshot-изображения через FileResponse**

```python
@router.get("/assignment-assets/{asset_id}")
async def assignment_asset(asset_id: int, user: dict = Depends(require_authenticated)):
    stored = await run_in_threadpool(actions.assignment_asset_get, asset_id, user)
    return file_response(stored, cache_control="private, max-age=3600")
```

Функцию `file_response` напишет задача 14; до неё маршрут временно возвращает
`Response(content=..., media_type=stored.mime_type)` через существующее чтение. Если задача 14 уже
выполнена — используйте `file_response` сразу.

- [ ] **Шаг 5: Прогнать тесты**

```bash
.venv/bin/python -m unittest tests.integration.test_api_flows tests.integration.test_assignment_assets -v
```

Ожидается: PASS без правки ожидаемых ответов.

- [ ] **Шаг 6: Коммит**

```bash
git add -A && git commit -m "Перевести действия работ и экспорта на функции"
```

---

### Задача 13: Перевести действия материалов

**Файлы:**
- Изменить: `src/trainer/api/controllers/materials.py`, `src/trainer/api/routes/materials.py`

**Интерфейсы:**
- Использует: `respond`, `FileResult`, зависимости задачи 8.
- Даёт: `materials_list(user)`, `materials_mine(user)`, `material_get(material_id, user)`,
  `material_create(payload, user, context)`, `material_update(material_id, payload, user, context)`,
  `material_publish(material_id, user, context)`, `material_delete(material_id, user, context)` →
  `ActionResult`; `material_asset_create(material_id, body: bytes, content_type: str, user, context) -> ActionResult`;
  `material_asset_get(asset_id, user) -> FileResult`.

- [ ] **Шаг 1: Зафиксировать эталон**

```bash
.venv/bin/python -m unittest tests.integration.test_materials -v
```

Ожидается: PASS.

- [ ] **Шаг 2: Перевести модуль по разделу «Правила перевода действия»**

`materials_list` и `material_get` доступны гостю: маршрут использует
`user: dict | None = Depends(current_user_or_none)`, а не `require_*`. Правило «гостю доступен только
`open-2026`» остаётся внутри действия без изменений.

- [ ] **Шаг 3: Перевести загрузку изображения**

Тело запроса читает маршрут и передаёт байтами:

```python
@router.post("/materials/{material_id}/assets")
async def create_asset(material_id: int, request: Request, user: dict = Depends(require_teacher)):
    body = await request.body()
    result = await run_in_threadpool(
        actions.material_asset_create,
        material_id,
        body,
        request.headers.get("Content-Type", ""),
        user,
        request_context(request),
    )
    return respond(result)
```

Лимит размера уже применён middleware задачи 9.

- [ ] **Шаг 4: Прогнать тесты**

```bash
.venv/bin/python -m unittest tests.integration.test_materials -v
```

Ожидается: PASS без правки ожидаемых ответов.

- [ ] **Шаг 5: Коммит**

```bash
git add -A && git commit -m "Перевести действия материалов на функции"
```

---

### Задача 14: Отдавать аудио через FileResponse с поддержкой Range

**Файлы:**
- Изменить: `src/trainer/infrastructure/storage/protocols.py`, `local.py`, `s3.py`
- Изменить: `src/trainer/services/recordings.py`
- Изменить: `src/trainer/api/controllers/recordings.py`, `src/trainer/api/routes/recordings.py`
- Изменить: `tests/integration/test_storage.py`, `tests/integration/test_api_flows.py`

**Интерфейсы:**
- Использует: `FileResult` (задача 7), `require_authenticated`, `require_student` (задача 8).
- Даёт:
  - `AudioStorage.local_path(key) -> Path | None` и `AudioStorage.stream(key) -> Iterator[bytes]`;
  - `services.recordings.storage_local_path(root, key)` и `services.recordings.stream_recording(root, key)`;
  - `routes.file_response(stored: FileResult, cache_control: str) -> Response` — используется также
    задачей 12.

- [ ] **Шаг 1: Написать падающий тест на Range**

Добавьте в `tests/integration/test_api_flows.py` в класс со сценарием записи:

```python
    def test_recording_supports_range_requests(self):
        recording_id, cookie = self.create_recording()
        status, headers, body = self.request_raw(
            f"/api/recordings/{recording_id}", cookie, headers={"Range": "bytes=0-3"}
        )

        self.assertEqual(status, 206)
        self.assertTrue(headers["Content-Range"].startswith("bytes 0-3/"))
        self.assertEqual(len(body), 4)
```

Вспомогательные `create_recording` и `request_raw` возьмите из существующих помощников этого файла;
если `request_raw` нет — добавьте его рядом с `request_bytes`, возвращая статус, заголовки и тело.

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.integration.test_api_flows -v -k range_requests
```

Ожидается: FAIL — статус 200 вместо 206.

- [ ] **Шаг 3: Расширить протокол хранилища**

В `src/trainer/infrastructure/storage/protocols.py`:

```python
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol


class AudioStorage(Protocol):
    def put(self, key: str, source: Path, content_type: str) -> None: ...
    def download(self, key: str, target: Path) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def local_path(self, key: str) -> Path | None: ...
    def stream(self, key: str) -> Iterator[bytes]: ...
```

В `local.py`:

```python
    def local_path(self, key: str) -> Path | None:
        target = self._path(key)
        return target if target.is_file() else None

    def stream(self, key: str) -> Iterator[bytes]:
        target = self._path(key)
        if not target.is_file():
            raise FileNotFoundError(key)
        with target.open("rb") as source:
            while chunk := source.read(64 * 1024):
                yield chunk
```

В `s3.py`:

```python
    def local_path(self, key: str) -> Path | None:
        return None

    def stream(self, key: str) -> Iterator[bytes]:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except Exception as error:
            self._raise_not_found(error, key)
        yield from body.iter_chunks(64 * 1024)
```

Добавьте `from collections.abc import Iterator` в оба модуля.

- [ ] **Шаг 4: Расширить сервис записей**

В `src/trainer/services/recordings.py`:

```python
def storage_local_path(root: Path, key: str) -> Path | None:
    return storage_from_env(root).local_path(key)


def stream_recording(root: Path, key: str) -> Iterator[bytes]:
    return storage_from_env(root).stream(key)
```

Добавьте `from collections.abc import Iterator`.

- [ ] **Шаг 5: Добавить помощник маршрута**

В `src/trainer/api/routes/__init__.py` рядом с `respond`:

```python
from fastapi.responses import FileResponse, Response, StreamingResponse

from trainer.api.runtime import AUDIO_DIR
from trainer.api.results import FileResult
from trainer.services.recordings import storage_local_path, stream_recording


def file_response(stored: FileResult, cache_control: str = "private, no-store") -> Response:
    headers = {"Cache-Control": cache_control, "X-Content-Type-Options": "nosniff"}
    path = storage_local_path(AUDIO_DIR, stored.key)
    if path is not None:
        return FileResponse(path, media_type=stored.mime_type, headers=headers)
    return StreamingResponse(stream_recording(AUDIO_DIR, stored.key), media_type=stored.mime_type, headers=headers)
```

- [ ] **Шаг 6: Перевести действия записей**

`recording_create` принимает тело байтами и параметры запроса аргументами; `recording_get` возвращает
`FileResult(key=row["file_name"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])` вместо
записи в `wfile`. Маршрут:

```python
@router.get("/recordings/{recording_id}")
async def recording(recording_id: int, user: dict = Depends(require_authenticated)):
    stored = await run_in_threadpool(actions.recording_get, recording_id, user)
    return file_response(stored)
```

- [ ] **Шаг 7: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.integration.test_api_flows -v -k range_requests
```

Ожидается: PASS с кодом 206.

- [ ] **Шаг 8: Проверить S3-путь**

```bash
.venv/bin/python -m unittest tests.integration.test_storage -v
```

Ожидается: PASS, включая тесты `local_path` и `stream` для обоих адаптеров. Если тестов на новые
методы нет — допишите их: `local_path` возвращает путь для локального адаптера и `None` для S3,
`stream` собирает те же байты, что и `read`.

- [ ] **Шаг 9: Коммит**

```bash
git add -A && git commit -m "Отдавать аудио через FileResponse с поддержкой Range"
```

---

### Задача 15: Удалить шим и зафиксировать границу транспорта

**Файлы:**
- Удалить: `src/trainer/api/http.py`, `src/trainer/api/controller.py`, `src/trainer/api/transport.py`
- Изменить: `src/trainer/api/dependencies.py` (удалить `ApiDependenciesMixin`)
- Изменить: `tests/unit/test_architecture_boundaries.py:56-72`

**Интерфейсы:**
- Использует: результаты задач 10–14 (все действия переведены).
- Даёт: в проекте остаётся один способ описать эндпоинт.

- [ ] **Шаг 1: Написать падающий тест границы**

В `tests/unit/test_architecture_boundaries.py` замените
`test_controller_keeps_route_and_legacy_actions` на:

```python
    def test_shim_is_removed(self):
        for name in ("http.py", "controller.py", "transport.py"):
            with self.subTest(name=name):
                self.assertFalse((PACKAGE / "api" / name).exists())

    def test_controllers_do_not_depend_on_the_web_framework(self):
        imports = imported_modules(PACKAGE / "api" / "controllers")
        forbidden = ("fastapi", "starlette")
        self.assertFalse(any(module.startswith(forbidden) for module in imports), imports)
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.unit.test_architecture_boundaries -v
```

Ожидается: FAIL — файлы шима ещё существуют.

- [ ] **Шаг 3: Удалить шим**

```bash
git rm src/trainer/api/http.py src/trainer/api/controller.py src/trainer/api/transport.py
```

В `src/trainer/api/dependencies.py` удалите класс `ApiDependenciesMixin` целиком: все его методы уже
существуют как функции модуля или перенесены в `services/accounts.py`.

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.unit.test_architecture_boundaries -v
```

Ожидается: PASS. Если падает правило про `fastapi` в контроллерах — вынесите оставшийся импорт в
маршрут: контроллер не должен знать про фреймворк.

- [ ] **Шаг 5: Полная проверка фазы**

```bash
make check && make test-e2e
```

Ожидается: зелёный прогон обоих.

```bash
.venv/bin/python -m scripts.s3_smoke
```

Ожидается: успешное завершение (требует запущенного MinIO; если его нет — зафиксируйте пропуск явно
и выполните проверку до слияния).

- [ ] **Шаг 6: Ручная проверка перемотки**

Запустите приложение, войдите преподавателем, откройте работу с аудиозаписью и перемотайте её в
плеере на середину. Это цель всей фазы, и автотест на 206 её не заменяет.

```bash
make run
```

- [ ] **Шаг 7: Коммит**

```bash
git add -A && git commit -m "Удалить шим BaseHTTPRequestHandler"
```

---

## Фаза 3. Точечные правки

### Задача 16: Упростить /api/health

**Файлы:**
- Изменить: `src/trainer/main.py:124-132`
- Изменить: `src/trainer/infrastructure/observability/service.py:60-86`, `__init__.py`
- Изменить: `tests/unit/test_observability.py`

**Интерфейсы:**
- Использует: результат задачи 3 (`engine_name` уже удалён).
- Даёт: `/api/health` отвечает `{"ok": true}` или 503 `{"ok": false}`.

- [ ] **Шаг 1: Написать падающий тест**

Добавьте в `tests/integration/test_asgi.py`:

```python
    def test_health_exposes_no_internal_counters(self):
        response = TestClient(app).get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.integration.test_asgi -v -k internal_counters
```

Ожидается: FAIL — в теле есть ключ `errors`.

- [ ] **Шаг 3: Упростить эндпоинт и удалить ErrorMonitor**

В `src/trainer/main.py`:

```python
@app.get("/api/health")
async def health():
    try:
        await run_in_threadpool(_check_database)
    except Exception:
        return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True}
```

Удалите импорт `error_monitor` и строку `error_monitor.observe(status)` в `observe_requests`.
В `src/trainer/infrastructure/observability/service.py` удалите класс `ErrorMonitor`, экземпляр
`error_monitor` и импорт `threading`, если он больше не нужен. Уберите оба имени из `__init__.py`
и из `__all__`. Удалите относящиеся к `ErrorMonitor` тесты в `tests/unit/test_observability.py`.

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.integration.test_asgi -v -k internal_counters && make check
```

Ожидается: PASS и зелёный `make check`.

- [ ] **Шаг 5: Коммит**

```bash
git add -A && git commit -m "Убрать внутренние счётчики из ответа health"
```

---

### Задача 17: Спрятать быстрый режим за ?debug=1

**Файлы:**
- Изменить: `frontend/js/shared/progress.js:19-26`
- Изменить: `frontend/js/runner/app.js:159,244-246`
- Изменить: `frontend/pages/index.html:63`
- Изменить: `tests-js/unit/views.test.js`

**Интерфейсы:**
- Использует: ничего.
- Даёт: `debugModeEnabled(search: string) -> boolean` в `frontend/js/shared/progress.js`.

- [ ] **Шаг 1: Написать падающий тест**

В `tests-js/unit/views.test.js`:

```javascript
test("fast mode stays off without the debug flag", () => {
  assert.equal(debugModeEnabled(""), false);
  assert.equal(debugModeEnabled("?debug=1"), true);
  assert.equal(sanitizeSettings({ fastMode: true }, "").fastMode, false);
  assert.equal(sanitizeSettings({ fastMode: true }, "?debug=1").fastMode, true);
});
```

Добавьте `debugModeEnabled` и `sanitizeSettings` в импорт из `../../frontend/js/shared/progress.js`.

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
node --test tests-js/unit/views.test.js
```

Ожидается: FAIL — `debugModeEnabled is not a function`.

- [ ] **Шаг 3: Реализовать функции**

В `frontend/js/shared/progress.js`:

```javascript
export function debugModeEnabled(search) {
  return new URLSearchParams(search || "").get("debug") === "1";
}

export function sanitizeSettings(settings, search) {
  const merged = { ...defaultProgress().settings, ...settings };
  return debugModeEnabled(search) ? merged : { ...merged, fastMode: false };
}
```

В `loadLocalProgress` пропустите настройки через `sanitizeSettings(saved.settings, location.search)`.

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
node --test tests-js/unit/views.test.js
```

Ожидается: PASS.

- [ ] **Шаг 5: Скрыть переключатель**

В `frontend/pages/index.html` добавьте классу переключателя признак скрытия по умолчанию:

```html
<label class="speed-switch hidden" id="fastModeSwitch"><input id="fastMode" type="checkbox"><span></span> Быстрый режим</label>
```

В `frontend/js/runner/app.js` при инициализации:

```javascript
if (debugModeEnabled(location.search)) $("fastModeSwitch").classList.remove("hidden");
```

Импортируйте `debugModeEnabled` из `../shared/progress.js`.

- [ ] **Шаг 6: Проверить в браузере**

Откройте главную страницу без флага — переключателя нет; с `?debug=1` — есть и работает.

- [ ] **Шаг 7: Прогнать проверки и закоммитить**

```bash
make check && make test-e2e
git add -A && git commit -m "Спрятать быстрый режим за отладочный флаг"
```

---

### Задача 18: Сделать шрифт PDF явной зависимостью

**Файлы:**
- Изменить: `src/trainer/infrastructure/exports.py:28-45`
- Изменить: `src/trainer/api/controllers/work.py` (действие экспорта)
- Изменить: `.env.example`
- Создать: тест в `tests/unit/test_infrastructure_services.py`

**Интерфейсы:**
- Использует: `ApiError` (задача 7).
- Даёт: `FontUnavailableError` в `trainer.infrastructure.exports`.

- [ ] **Шаг 1: Написать падающий тест**

В `tests/unit/test_infrastructure_services.py`:

```python
    def test_pdf_export_refuses_to_build_without_a_font(self):
        from trainer.infrastructure.exports import FontUnavailableError, submissions_pdf

        with patch.dict(os.environ, {"TRAINER_PDF_FONT": "/nonexistent/font.ttf"}):
            with self.assertRaises(FontUnavailableError):
                submissions_pdf([])
```

Импорты `os`, `patch` в файле уже есть; если нет — добавьте.

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.unit.test_infrastructure_services -v -k without_a_font
```

Ожидается: FAIL — `ImportError: cannot import name 'FontUnavailableError'`.

- [ ] **Шаг 3: Реализовать**

В `src/trainer/infrastructure/exports.py`:

```python
DEFAULT_PDF_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


class FontUnavailableError(RuntimeError):
    """Шрифт с кириллицей недоступен: PDF без него нечитаем."""
```

В `submissions_pdf` замените выбор шрифта:

```python
    font_path = Path(os.environ.get("TRAINER_PDF_FONT", DEFAULT_PDF_FONT))
    if not font_path.is_file():
        raise FontUnavailableError(f"Шрифт для PDF не найден: {font_path}")
    pdfmetrics.registerFont(TTFont("DejaVu", font_path))
    font = "DejaVu"
```

Добавьте `import os` в начало модуля. Фолбэк на Helvetica удалите: он молча ломает кириллицу.

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.unit.test_infrastructure_services -v -k without_a_font
```

Ожидается: PASS.

- [ ] **Шаг 5: Перевести исключение в ответ API**

В действии `teacher_export` (`src/trainer/api/controllers/work.py`) оберните вызов:

```python
    try:
        data = submissions_pdf(items)
    except FontUnavailableError as error:
        raise ApiError("pdf_font_unavailable", "PDF недоступен: не установлен шрифт с кириллицей", 503) from error
```

- [ ] **Шаг 6: Задокументировать переменную**

В `.env.example` добавьте:

```
# Шрифт с кириллицей для PDF-экспорта; в Docker-образе установлен fonts-dejavu-core.
TRAINER_PDF_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
```

- [ ] **Шаг 7: Прогнать проверки и закоммитить**

```bash
make check
git add -A && git commit -m "Сделать шрифт PDF явной зависимостью экспорта"
```

---

### Задача 19: Вернуть нативный select

**Файлы:**
- Удалить: `frontend/js/shared/project-select.js`
- Изменить: файлы, импортирующие его (найти поиском)
- Изменить: `frontend/styles/base.css` (правила `.project-select*`)

**Интерфейсы:**
- Использует: ничего.
- Даёт: отсутствие модуля `project-select.js`.

- [ ] **Шаг 1: Найти потребителей**

```bash
grep -rn "project-select" frontend tests-js tests-e2e
```

Запишите список файлов — их нужно поправить на шаге 2.

- [ ] **Шаг 2: Убрать импорты и вызовы**

Удалите импорт `project-select.js` и вызовы его функции инициализации во всех найденных файлах.

- [ ] **Шаг 3: Удалить модуль**

```bash
git rm frontend/js/shared/project-select.js
```

- [ ] **Шаг 4: Перенести оформление на нативный элемент**

В `frontend/styles/base.css` замените правила `.project-select`, `.project-select-trigger`,
`.project-select-menu`, `.project-select-value`, `.project-select-native` одним правилом для `select`,
сохранив текущие цвета, скругление, отступы и шрифт:

```css
select {
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'%3E%3Cpath fill='%238b1a1a' d='M1 1l5 5 5-5'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 32px;
}
```

Остальные свойства (фон, рамка, типографика) возьмите из удаляемых правил.

- [ ] **Шаг 5: Проверить в браузере**

Откройте страницы с выпадающими списками (кабинет, каталог, редактор материала) и сравните с
прежним оформлением. Расхождения устраняйте стилями, не возвращая скрипт.

- [ ] **Шаг 6: Прогнать проверки и закоммитить**

```bash
make check && make test-e2e
git add -A && git commit -m "Вернуть нативный выпадающий список"
```

---

### Задача 20: Вынести импортёр банка ФИПИ в tools/

**Файлы:**
- Переместить: `scripts/speaking_bank.py`, `scripts/import_speaking_bank.py` → `tools/speaking-bank/`
- Переместить: `tests/unit/test_speaking_bank.py`, `tests/unit/test_speaking_bank_import.py` → `tools/speaking-bank/tests/`
- Создать: `tools/speaking-bank/README.md`
- Изменить: `pyproject.toml` (исключение `tools` из ruff при необходимости)

**Интерфейсы:**
- Использует: ничего.
- Даёт: `make test` не запускает тесты импортёра.

- [ ] **Шаг 1: Переместить файлы**

```bash
mkdir -p tools/speaking-bank/tests
git mv scripts/speaking_bank.py tools/speaking-bank/speaking_bank.py
git mv scripts/import_speaking_bank.py tools/speaking-bank/import_speaking_bank.py
git mv tests/unit/test_speaking_bank.py tools/speaking-bank/tests/test_speaking_bank.py
git mv tests/unit/test_speaking_bank_import.py tools/speaking-bank/tests/test_speaking_bank_import.py
```

- [ ] **Шаг 2: Поправить импорты**

В перемещённых файлах замените `from scripts.speaking_bank import ...` на
`from speaking_bank import ...`. Тесты запускаются из каталога инструмента.

- [ ] **Шаг 3: Написать README инструмента**

Создайте `tools/speaking-bank/README.md`:

```markdown
# Импортёр банка ФИПИ

Одноразовый инструмент: разбирает выгрузку открытого банка заданий ФИПИ и собирает из неё варианты
`bank-NN` в `content/variants/` вместе с изображениями в `public/assets/variants/2026/`.

Не входит в `make test`, `make check` и CI: инструмент запускается вручную при обновлении банка.

## Запуск

```bash
cd tools/speaking-bank
PYTHONPATH=.:../../src ../../.venv/bin/python import_speaking_bank.py plan --source <каталог выгрузки>
PYTHONPATH=.:../../src ../../.venv/bin/python import_speaking_bank.py build --source <каталог выгрузки>
```

## Тесты

```bash
cd tools/speaking-bank
PYTHONPATH=.:../../src ../../.venv/bin/python -m unittest discover -s tests -v
```
```

- [ ] **Шаг 4: Проверить, что тесты инструмента ещё работают**

```bash
cd tools/speaking-bank && PYTHONPATH=.:../../src ../../.venv/bin/python -m unittest discover -s tests -v; cd ../..
```

Ожидается: PASS.

- [ ] **Шаг 5: Проверить, что основной набор их больше не запускает**

```bash
make test-unit 2>&1 | grep -c speaking_bank
```

Ожидается: `0`.

- [ ] **Шаг 6: Прогнать проверки и закоммитить**

```bash
make check
git add -A && git commit -m "Вынести импортёр банка ФИПИ в отдельный инструмент"
```

---

### Задача 21: Сгруппировать каталог вариантов

**Файлы:**
- Изменить: `frontend/js/catalog/variant-catalog.js`
- Изменить: `frontend/js/catalog/variants-page.js`
- Изменить: `frontend/styles/pages/variants.css`
- Изменить: `tests-js/unit/views.test.js`

**Интерфейсы:**
- Использует: `variantKind(id)` — уже есть в модуле.
- Даёт: `groupVariants(variants) -> Array<{title: string, collapsed: boolean, items: Array}>`.

- [ ] **Шаг 1: Написать падающий тест**

В `tests-js/unit/views.test.js`:

```javascript
test("catalog groups variants by source", () => {
  const groups = groupVariants([
    { id: "open-2026", label: "Официальный" },
    { id: "demo-2025", label: "Демо" },
    { id: "bank-01", label: "Банк 01" },
  ]);
  assert.deepEqual(groups.map(group => group.title), ["Официальный вариант", "Демоверсии", "Банк ФИПИ"]);
  assert.equal(groups[2].collapsed, true);
  assert.equal(groups[0].collapsed, false);
});
```

Добавьте `groupVariants` в импорт из `../../frontend/js/catalog/variant-catalog.js`.

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
node --test tests-js/unit/views.test.js
```

Ожидается: FAIL — `groupVariants is not a function`.

- [ ] **Шаг 3: Реализовать группировку**

В `frontend/js/catalog/variant-catalog.js`:

```javascript
const GROUPS = [
  { title: "Официальный вариант", prefix: "open-", collapsed: false },
  { title: "Демоверсии", prefix: "demo-", collapsed: false },
  { title: "Банк ФИПИ", prefix: "bank-", collapsed: true },
];

export function groupVariants(variants) {
  const authored = variants.filter(variant => !GROUPS.some(group => variant.id.startsWith(group.prefix)));
  const groups = GROUPS.map(group => ({
    title: group.title,
    collapsed: group.collapsed,
    items: variants.filter(variant => variant.id.startsWith(group.prefix)),
  }));
  if (authored.length) groups.push({ title: "Авторские материалы", collapsed: false, items: authored });
  return groups.filter(group => group.items.length);
}
```

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
node --test tests-js/unit/views.test.js
```

Ожидается: PASS.

- [ ] **Шаг 5: Отрисовать группы**

В `variants-page.js` оберните вызов `catalogMarkup` в перебор групп:

```javascript
const markup = groupVariants(filtered).map(group => `
  <details class="variant-group"${group.collapsed ? "" : " open"}>
    <summary>${group.title} <span>${group.items.length}</span></summary>
    <div class="variant-grid">${catalogMarkup(group.items)}</div>
  </details>`).join("");
```

Добавьте в `frontend/styles/pages/variants.css` правила для `.variant-group` и `.variant-group summary`
в стиле существующих карточек.

- [ ] **Шаг 6: Проверить в браузере и закоммитить**

Откройте «Все варианты»: группа банка свёрнута, остальные раскрыты, поиск и фильтр по годам работают.

```bash
make check && make test-e2e
git add -A && git commit -m "Сгруппировать каталог вариантов по источнику"
```

---

### Задача 22: Убрать мусор из дерева и черновики планов

**Файлы:**
- Удалить с диска: `backend/`, `api/`, `assets/`, `data/`, все `.DS_Store`
- Изменить: `.gitignore`, `scripts/check_repository_hygiene.py:8`
- Изменить: `tests/unit/test_repository_hygiene.py`
- Перестать отслеживать: `docs/superpowers/plans/`

**Интерфейсы:**
- Использует: ничего.
- Даёт: чистое рабочее дерево.

- [ ] **Шаг 1: Написать падающий тест**

В `tests/unit/test_repository_hygiene.py`:

```python
    def test_plan_drafts_are_not_tracked(self):
        failures = check_repository(Path("/repo"), ["docs/superpowers/plans/2026-07-30-project-cleanup.md"])

        self.assertEqual(len(failures), 1)
        self.assertIn("docs/superpowers/plans/", failures[0])
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

```bash
.venv/bin/python -m unittest tests.unit.test_repository_hygiene -v -k plan_drafts
```

Ожидается: FAIL — `0 != 1`.

- [ ] **Шаг 3: Расширить правило гигиены**

В `scripts/check_repository_hygiene.py`:

```python
FORBIDDEN_PREFIXES = (
    "var/",
    "backups/",
    "tmp/",
    "test-results/",
    "playwright-report/",
    "docs/superpowers/plans/",
)
```

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

```bash
.venv/bin/python -m unittest tests.unit.test_repository_hygiene -v -k plan_drafts
```

Ожидается: PASS.

- [ ] **Шаг 5: Убрать планы из индекса и добавить в .gitignore**

```bash
git rm -r --cached docs/superpowers/plans
printf 'docs/superpowers/plans/\n' >> .gitignore
```

Файлы остаются на диске — они нужны для выполнения этого плана.

- [ ] **Шаг 6: Вычистить рабочее дерево**

```bash
rm -rf backend api assets data
find . -name .DS_Store -not -path "./.git/*" -not -path "./node_modules/*" -delete
```

Убедитесь, что удаляются именно пустые каталоги-остатки: `git status` до и после не должен показывать
изменений в отслеживаемых файлах.

- [ ] **Шаг 7: Прогнать проверки и закоммитить**

```bash
make check
git add -A && git commit -m "Убрать остатки прежней структуры и черновики планов"
```

---

### Задача 23: Пересчитать порог покрытия и закрыть работу

**Файлы:**
- Изменить: `pyproject.toml:33`
- Изменить: `CLAUDE.md`, `DEVELOPMENT.md`, `README.md`, `AGENTS.md` — упоминания удалённого
- Изменить: `docs/architecture.md`

**Интерфейсы:**
- Использует: результаты всех предыдущих задач.
- Даёт: зелёный `make check` на актуальном пороге и документацию без ссылок на удалённое.

- [ ] **Шаг 1: Измерить фактическое покрытие**

```bash
make test
```

Запишите итоговый процент из строки `TOTAL`.

- [ ] **Шаг 2: Поднять порог**

В `pyproject.toml` установите `fail_under` равным фактическому проценту, округлённому вниз до
целого, но не ниже 70:

```toml
fail_under = <фактический процент>
```

- [ ] **Шаг 3: Проверить, что порог держится**

```bash
make test
```

Ожидается: зелёный прогон без предупреждения о покрытии.

- [ ] **Шаг 4: Вычистить документацию**

Пройдите поиском по упоминаниям удалённого и уберите их:

```bash
grep -rn "PostgreSQL\|postgres\|DATABASE_URL\|legacy/\|транскрипц\|transcription\|compose.scale" README.md CLAUDE.md AGENTS.md DEVELOPMENT.md SECURITY.md CONTRIBUTING.md docs/architecture.md docs/README.md docs/runbooks
```

Для каждого попадания: либо удалите абзац, либо перепишите его под текущее состояние. В
`CLAUDE.md` обновите раздел «База данных» (один движок вместо двух), раздел про `legacy/` удалите,
в списке команд уберите `make docker-check` для `compose.scale.yml`.

В `docs/runbooks/backup-restore.md` удалите процедуру восстановления PostgreSQL.

- [ ] **Шаг 5: Финальная проверка**

```bash
make check && make test-e2e && make docker-build
```

Ожидается: все три зелёные.

```bash
docker compose config --quiet
```

Ожидается: успешный разбор без `compose.scale.yml`.

- [ ] **Шаг 6: Коммит**

```bash
git add -A && git commit -m "Пересчитать порог покрытия и обновить документацию"
```

---

## Порядок и зависимости

| Задача | Зависит от | Можно ли параллельно |
| --- | --- | --- |
| 1 | — | да, с 2 |
| 2 | — | да, с 1 |
| 3 | 2 | нет |
| 4 | 3 | нет |
| 5 | 4 | нет |
| 6 | 4, 5 | нет |
| 7 | фаза 1 завершена | нет |
| 8 | 7 | нет |
| 9 | 7 | да, с 8 |
| 10 | 8, 9 | нет |
| 11–13 | 10 | да, между собой |
| 14 | 10 | да, с 11–13 |
| 15 | 10–14 | нет |
| 16 | 3, 15 | да, с 17–22 |
| 17, 19, 21 | 15 | да, между собой |
| 18 | 7, 12 | да, с 16–22 |
| 20, 22 | — | да, с 16–21 |
| 23 | все | нет |
