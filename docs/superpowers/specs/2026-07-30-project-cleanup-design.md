# Чистка проекта: транспорт, необязательные подсистемы и мусор

## Цель

Убрать из проекта подсистемы, которые не используются в эксплуатации, но продолжают требовать
сопровождения, и заменить эмуляцию `BaseHTTPRequestHandler` нативным транспортом FastAPI.

Задачи в порядке убывания цены сопровождения:

1. снять шим `BaseHTTPRequestHandler`, из-за которого ответы буферизуются в памяти, аудио отдаётся без
   Range, а в `transport.py` живёт мёртвый код с обращениями к несуществующим методам;
2. удалить ветку PostgreSQL: она не используется в эксплуатации, но обязывает вручную поддерживать список
   `IDENTITY_TABLES` и паритет схем в CI;
3. удалить `legacy/` — compatibility runtime, срок жизни которого истёк;
4. удалить стек транскрипции: он выключен по умолчанию и содержит неработающую настройку языка;
5. точечные правки: `/api/health`, «Быстрый режим», шрифт PDF, `project-select`, вынос ETL банка ФИПИ,
   мусор в рабочем дереве и черновики планов в `docs/`.

Набор URL и семантика ответов сохраняются: ни один маршрут не переименовывается, не меняет метод и не
меняет коды успеха. Намеренных изменений тела ответа ровно два, оба описаны ниже: из `/api/health` уходят
поля `database` и `errors`, из записей в ответах преподавателю — поля расшифровки. Всё остальное —
статусы, форматы ошибок, заголовки, cookie — остаётся байт-в-байт прежним, и это критерий приёмки фазы 2.

Проект находится на стадии прототипа. Обратная совместимость с развёрнутыми экземплярами PostgreSQL и с
сохранёнными расшифровками не требуется.

## Ограничения, определяющие порядок работ

Два факта в коде делают наивный порядок работ невозможным.

`migrations/versions/20260705_01_initial_postgres.py` импортирует `POSTGRES_SCHEMA` из
`trainer.infrastructure.database.postgres` на уровне модуля. Alembic загружает все файлы ревизий при любой
операции, поэтому удаление `postgres.py` ломает миграции целиком, включая SQLite.

Таблица `transcription_jobs` и колонки `transcript_status`, `transcript_text`, `transcript_error`,
`transcribed_at` созданы в `migration_005_transcriptions` — то есть в замороженном SQLite-baseline 1–7,
редактирование которого запрещено ADR 0003. Снять их можно только новой Alembic-ревизией.

Отсюда порядок: сначала удаления (фаза 1), затем снятие шима (фаза 2), затем точечные правки (фаза 3).
Удаления уменьшают площадь переделки транспорта: из `test_migrations.py` уходит ветка PostgreSQL, из
`recordings.py` — путь постановки задания на расшифровку, из `transport.py` — единственный потребитель
`serve_static`.

## Фаза 1. Удаление PostgreSQL

### Что удаляется

- `src/trainer/infrastructure/database/postgres.py` целиком;
- `compose.scale.yml`;
- `scripts/postgres_smoke.py`, `scripts/postgres_restore_smoke.py`;
- `psycopg[binary,pool]` из `requirements.txt`;
- установка репозитория PGDG, `gnupg` и `postgresql-client-16` из `Dockerfile`;
- сервис `postgres`, установка `postgresql-client` и шаг «Test PostgreSQL adapter» из
  `.github/workflows/ci.yml`;
- вторая строка `docker compose config` в цели `docker-check` в `Makefile`;
- переменные `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` и закомментированный `DATABASE_URL`
  из `.env.example`.

### Что меняется

`infrastructure/database/core.py` перестаёт читать `DATABASE_URL`. `connect()` открывает SQLite и выполняет
`PRAGMA journal_mode = WAL` дополнительно к существующему `PRAGMA foreign_keys = ON`; WAL сейчас не включён,
и его включение — единственная компенсация за отказ от PostgreSQL. `initialize()` всегда вызывает
`upgrade_sqlite_database`. Функции `engine_name()` и `close_connections()` удаляются, вместе с ними —
вызов `close_connections()` в lifespan `main.py`. Константа `INTEGRITY_ERRORS` перестаёт быть кортежем с
`psycopg.IntegrityError` и становится `sqlite3.IntegrityError`.

`infrastructure/database/migrations.py` теряет `normalize_database_url`, PostgreSQL-ветку
`upgrade_database` вместе с advisory-блокировкой, `MIGRATION_LOCK_KEY` и `MIGRATION_LOCK_TIMEOUT_MS`.
Остаётся путь SQLite: применить baseline 1–7, проверить полный список версий, при отсутствии
`alembic_version` штампануть `20260711_03`, выполнить `upgrade head`.

`scripts/backup.py` теряет ветку `pg_dump` и чтение `DATABASE_URL`; остаётся резервное копирование файла
SQLite и аудио.

`tests/integration/test_migrations.py` теряет класс PostgreSQL-теста и проверку паритета схем; остаётся
SQLite-часть: чистая база, обновление существующей базы, повторный `upgrade head`.

### Ревизия `20260705_01`

Ревизию нельзя удалить: она стартовая в цепочке (`down_revision = None`), и на неё опирается штамп
`20260711_03` в существующих базах SQLite.

Литерал `POSTGRES_SCHEMA` переносится из `postgres.py` внутрь файла ревизии как приватная константа
модуля. Тело `upgrade()` и `downgrade()` не меняется. Это формально правка опубликованной ревизии, что
запрещено ADR 0003; правка допускается, поскольку она механическая, поведение для PostgreSQL сохраняется
байт-в-байт, а исполняться эта ветка после удаления PostgreSQL уже не может.

### ADR

Добавляется `docs/decisions/0004-sqlite-only-storage.md` со статусом Accepted. Он фиксирует SQLite как
единственный движок, отменяет требование dual-dialect и паритета схем из ADR 0003 и разрешает описанную
правку `20260705_01`. ADR 0003 переводится в статус Superseded by 0004; сам текст ADR 0003 не
переписывается — правило «не редактировать опубликованные решения» распространяется и на ADR.

Требование ADR 0003 «Alembic — канонический владелец изменений схемы» и заморозка baseline 1–7 сохраняются.

## Фаза 1. Удаление `legacy/`

Удаляется каталог `legacy/` целиком: `server.py`, `README.md`, `__init__.py`, `tests/`.

`tests/unit/test_package_layout.py` содержит проверку, что основной код не импортирует `legacy`. Она
заменяется на проверку, что каталога `legacy/` не существует.

`docs/decisions/0001-fastapi-runtime.md` переводится в статус Accepted (implemented): его единственное
ограничение — «каталог `legacy/` удаляется после одного стабильного релизного цикла» — выполнено. Текст
решения не переписывается, добавляется строка статуса.

Ссылка на `legacy/README.md` удаляется из `README.md`.

## Фаза 1. Удаление стека транскрипции

### Что удаляется

- `src/trainer/services/transcription.py`;
- `src/trainer/workers/transcription.py` и пакет `workers/`, если он остаётся пустым;
- `src/trainer/infrastructure/transcription.py`;
- `scripts/transcription_worker.py`;
- `openai` из `requirements.txt`;
- сервис `transcription-worker` с профилем `transcription` из `compose.yml`;
- `TRAINER_TRANSCRIPTION_ENABLED`, `OPENAI_API_KEY`, `OPENAI_TRANSCRIPTION_MODEL` и
  `TRAINER_TRANSCRIPTION_LANGUAGE` из `.env.example`;
- `docs/runbooks/transcription-worker.md`;
- шаг worker smoke из `.github/workflows/ci.yml`.

`tests/integration/test_storage_transcription.py` переименовывается в `test_storage.py`. Из него уходят
тесты транскрипции и импорт `POSTGRES_SCHEMA`, `IDENTITY_TABLES`, `Connection` из удалённого
`postgres.py`; остаются тесты локального и S3-хранилища.

Переменная `TRAINER_TRANSCRIPTION_LANGUAGE` в `.env.example` никогда не читалась: код обращается к
`OPENAI_TRANSCRIPTION_LANGUAGE`. Это расхождение — одно из оснований удаления, а не дефект, который нужно
чинить перед удалением.

### Что меняется в коде

`api/controllers/recordings.py` перестаёт импортировать `enabled` и `enqueue`. Колонка
`transcript_status` уходит из `INSERT` в `recordings`, постановка задания в очередь удаляется.

Ответы преподавателю перестают включать поля `transcript_status` и `transcript_text` в записях. На
фронтенде удаляется функция `transcriptMarkup` и её вызов в `frontend/js/account/account-view.js`,
правила `.recording-transcript` и `.transcript-status` в `frontend/styles/base.css`, а также относящиеся
к расшифровке ожидания в `tests-js/unit/views.test.js`.

### Схема

Новая Alembic-ревизия `20260730_05_drop_transcription` после текущего head:

- `DROP TABLE transcription_jobs` (вместе с индексом `transcription_jobs_queue_idx`);
- удаление колонок `transcript_status`, `transcript_text`, `transcript_error`, `transcribed_at` из
  `recordings` через `batch_alter_table`.

SQLite-baseline 1–7 не редактируется. На чистой базе объекты по-прежнему создаются миграцией 5, а затем
сразу удаляются новой ревизией. Это прямое следствие правила заморозки baseline и принимается сознательно:
альтернатива — редактирование baseline — ломает существующие базы.

`downgrade()` восстанавливает таблицу и колонки в исходном виде, чтобы ревизия оставалась обратимой.

## Фаза 2. Снятие шима `BaseHTTPRequestHandler`

### Что удаляется

- `src/trainer/api/http.py` (функция `invoke` и сборка контроллера через `object.__new__`);
- `src/trainer/api/controller.py` (класс `ApiController`);
- `src/trainer/api/transport.py` целиком, включая мёртвые `serve_static` и `log_message`, которые
  обращаются к отсутствующим `self.send_error` и `self.address_string`.

### Во что превращаются контроллеры

Каждый mixin из `api/controllers/` становится модулем обычных синхронных функций. Функция принимает
явные аргументы и возвращает данные; она не знает про HTTP-транспорт:

```python
def teacher_dashboard(user: dict) -> dict: ...
def material_update(material_id: int, payload: MaterialUpdate, user: dict) -> dict: ...
def recording_get(recording_id: int, user: dict) -> FileResult: ...
```

`FileResult` — небольшой dataclass с полями `key`, `mime_type`, `size_bytes`, общий для аудиозаписей и
snapshot-изображений назначения. Он описывает, что отдать, но сам ничего не читает; чтение выполняет
маршрут.

Маршрут в `api/routes/` вызывает функцию через `run_in_threadpool` и превращает результат в ответ.
Возврат `dict` становится `JSONResponse`; возврат дескриптора файла — `FileResponse`.

### Замена возможностей транспорта

| Было в `ApiTransportMixin` | Стало |
| --- | --- |
| `read_json()` | Pydantic-схема приходит аргументом маршрута; ручной разбор тела не нужен |
| `send_json(payload)` | функция возвращает `dict`, маршрут формирует `JSONResponse` |
| `send_json(..., token=...)` | функция возвращает данные и сессионный токен; cookie ставит маршрут одной общей функцией `set_session_cookie` |
| `send_error_json(status, message, code)` | исключение `ApiError(code, message, status)` |
| `send_bytes(data, type, filename)` | `Response` с `Content-Disposition` в маршруте |
| `same_origin_request()` | middleware в `main.py` для POST/PUT/DELETE |
| `serve_static()` | удаляется; статику отдаёт catch-all маршрут `main.py`, он уже существует |
| `require_role()` | зависимость `Depends(require_teacher)` / `Depends(require_student)` |

`ApiError` определяется в `api/errors.py` рядом с существующими `error_payload` и `default_error_code`.
Обработчик исключения регистрируется в `main.py` и сохраняет текущее поведение `send_error_json`: тот же
формат тела, тот же статус и то же событие лога `api_error` с полями `code`, `status`, `path`.

`require_role` меняет контракт с «вернул `None` — вызывающий обязан немедленно сделать `return`» на «бросил
`ApiError`». Нынешний контракт — источник тихих ошибок: пропущенный `return` после отказа приводит к
выполнению действия без прав.

Коды и статусы отказа сохраняются как есть: 401 `authentication_required`, 403 в остальных случаях,
публичные коды `email_verification_required` и `teacher_not_allowed` продолжают попадать в тело ответа,
прочие причины отказа — нет. Решение по-прежнему принимает `authorize_role` из `domain/accounts`.

### Отдача файлов

`recording_get` и `assignment_asset_get` перестают читать файл в память. Протокол `AudioStorage`
получает два метода:

- `local_path(key) -> Path | None` — путь на диске для `LocalAudioStorage`, `None` для `S3AudioStorage`;
- `stream(key) -> Iterator[bytes]` — чтение по частям.

Маршрут отдаёт `FileResponse`, если `local_path` вернул путь: Range-запросы и ответы 206 обрабатывает
Starlette. Это чинит перемотку в браузерном плеере и убирает удержание всего файла в памяти.

Иначе маршрут отдаёт `StreamingResponse` поверх `stream(key)` — без поддержки Range. Перемотка работает
только на локальном хранилище; проброс Range в S3 в объём работ не входит. Метод `read(key)` остаётся в
протоколе: им пользуются тесты и сценарии, где нужен весь файл целиком.

Загрузка аудио (`recording_create`) продолжает читать тело целиком: лимит `MAX_AUDIO_BODY` уже применяется,
а `validate_duration` требует файла на диске.

### Ограничение размера тела

Потоковая проверка лимита, которая сейчас живёт в `invoke`, переносится в middleware `main.py` рядом с
существующим `reject_oversized_json`. Лимит `MAX_AUDIO_BODY` применяется к маршрутам загрузки аудио и
изображений материала, `MAX_BODY` — ко всем остальным. Выбор лимита по имени действия заменяется
явным параметром маршрута.

### Границы и тесты

Тест `tests/unit/test_architecture_boundaries.py` дополняется правилом: модули `api/controllers/` не
импортируют `fastapi` и `starlette`. Это фиксирует, что действия остались свободными от транспорта.

Интеграционные тесты правятся только там, где они обращались к внутренностям контроллера. Ожидаемые
статусы, тела и заголовки ответов не меняются — расхождение здесь означает сломанный контракт, а не
устаревший тест.

## Фаза 3. Точечные правки

### `/api/health`

Эндпоинт возвращает `{"ok": true}` при доступной базе и `{"ok": false}` со статусом 503 при недоступной.
Поля `database` и `errors` удаляются: первое теряет смысл после удаления PostgreSQL, второе публиковало
внутренние счётчики ошибок без авторизации.

Класс `ErrorMonitor` и вызов `error_monitor.observe(status)` удаляются из `observability`. Счётчик был
монотонным, жил в памяти одного процесса и не давал ни скорости ошибок, ни их сброса — как мониторинг он
не работал.

Это единственное намеренное изменение публичного контракта. `HEALTHCHECK` в `Dockerfile` и smoke-шаг CI
проверяют код ответа, а не тело, и продолжают работать.

### Быстрый режим

Чекбокс `#fastMode` отображается только при `?debug=1` в URL. Без флага элемент скрыт, а сохранённое
`progress.settings.fastMode` игнорируется и приводится к `false` при загрузке. Ученик не может случайно
включить сокращённые тайминги и тренироваться в неэкзаменационном режиме.

Быстрый режим не используется в E2E-сценариях; он фигурирует только в `tests-js/unit/views.test.js` как
часть слияния настроек прогресса. Эти тесты дополняются случаем «сохранён `fastMode: true`, флага нет →
режим выключен».

### Шрифт PDF

Путь к шрифту берётся из `TRAINER_PDF_FONT`, по умолчанию —
`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`. Если файла нет, `submissions_pdf` бросает
`FontUnavailableError` вместо молчаливого перехода на Helvetica, который превращает кириллицу в
нечитаемый набор символов.

Исключение объявляется в `infrastructure/exports.py`: `infrastructure/` не имеет права импортировать
`trainer.api`, и это проверяется тестом границ. Действие экспорта ловит его и поднимает `ApiError` с
кодом `pdf_font_unavailable` и статусом 503. Пакет `fonts-dejavu-core` остаётся в `Dockerfile`, поэтому
в production путь ошибки недостижим; она рассчитана на локальный запуск вне Docker.

CSV-экспорт и оба маршрута экспорта сохраняются без изменений.

### `project-select`

`frontend/js/shared/project-select.js` удаляется. Элементы `<select>` остаются нативными; их внешний вид
задаётся CSS в существующих файлах стилей. Ручная реализация `role="listbox"` на 113 строк убирается
вместе с рисками для доступности и мобильной клавиатуры.

Визуальный результат проверяется в браузере после изменения; расхождение с текущим оформлением
устраняется стилями, а не возвратом скрипта.

### Вынос ETL банка ФИПИ

`scripts/speaking_bank.py`, `scripts/import_speaking_bank.py` и тесты `tests/unit/test_speaking_bank.py`,
`tests/unit/test_speaking_bank_import.py` переносятся в `tools/speaking-bank/` вместе со своим `README.md`,
описывающим запуск. Каталог `tools/` не входит в `make test`, `make check` и CI.

`Pillow` остаётся в `requirements.txt`: он нужен импортёру, а импортёр остаётся частью репозитория.
Это осознанная плата за сохранение воспроизводимости импорта.

Покрытие coverage считается по `source = ["trainer"]`, поэтому вынос скриптов на него не влияет — он
сокращает время `make test`. На порог `fail_under = 70` влияет удаление кода `trainer`: `postgres.py`,
сервис транскрипции и `transport.py`. Порог перепроверяется по фактическому отчёту после фазы 3 и
поднимается, если фактическое покрытие выросло; понижать порог запрещено.

### Каталог вариантов

Список из 34 позиций в `frontend/js/catalog/variant-catalog.js` группируется по источнику: «Официальный
вариант», «Демоверсии», «Банк ФИПИ». Группа банка свёрнута по умолчанию. Формат `content/variants/index.json`
не меняется — группа выводится из префикса идентификатора (`open-`, `demo-`, `bank-`).

### Мусор в дереве и документации

С диска удаляются пустые каталоги-остатки прежней структуры: `backend/`, `api/`, `assets/`, `data/`.
Они не отслеживаются Git и содержат только `.DS_Store` и `__pycache__`, но сбивают навигацию по проекту.
Файлы `.DS_Store` удаляются из рабочего дерева; в `.gitignore` проекта они уже перечислены, так что
настройка глобального `~/.gitignore` не требуется и в объём работ не входит.

`docs/superpowers/plans/` перестаёт отслеживаться Git и добавляется в `.gitignore`: это черновики процесса
на 2160 строк, которые описывают уже выполненную работу и расходятся с кодом. `docs/superpowers/specs/`
и `docs/decisions/` остаются — они описывают решения, а не ход работ.

`scripts/check_repository_hygiene.py` дополняется запретом на отслеживание `docs/superpowers/plans/`.

## Тестирование

Работа ведётся по циклам red-green внутри каждой фазы. Удаление кода проверяется тестами, которые
фиксируют отсутствие удалённого, а не только зелёный прогон остального.

Фаза 1:

1. Тест миграций на чистой базе SQLite подтверждает отсутствие таблицы `transcription_jobs` и колонок
   `transcript_*` после `upgrade head`.
2. Тест миграций на базе, созданной до новой ревизии, подтверждает успешный `upgrade head` и то же
   конечное состояние схемы.
3. Тест подтверждает обратимость: `downgrade` на один шаг возвращает таблицу и колонки.
4. `test_package_layout.py` подтверждает отсутствие каталога `legacy/`.
5. Тест подтверждает, что `journal_mode` открытого соединения равен `wal`.
6. Интеграционный тест создания записи подтверждает, что запись сохраняется без полей расшифровки.

Фаза 2:

7. Существующие интеграционные тесты `tests/integration/test_api_flows.py`, `test_accounts.py`,
   `test_materials.py`, `test_assignment_assets.py` проходят без изменения ожидаемых ответов.
8. Новый тест подтверждает, что `GET /api/recordings/{id}` с заголовком `Range: bytes=0-10` возвращает
   206 и корректный `Content-Range` на локальном хранилище.
9. Новый тест подтверждает, что отказ `require_role` возвращает 401 без сессии и 403 при неподходящей роли,
   что тело содержит прежние публичные коды и что действие при этом не выполняется.
10. `test_architecture_boundaries.py` подтверждает отсутствие импортов `fastapi` и `starlette` в
    `api/controllers/`.

Фаза 3:

11. Тест подтверждает, что `/api/health` не содержит полей `errors` и `database`.
12. JS-тест подтверждает, что без `?debug=1` быстрый режим выключен независимо от сохранённого состояния.
13. Тест подтверждает, что `submissions_pdf` при отсутствии файла шрифта бросает `FontUnavailableError`,
    а маршрут экспорта отвечает 503 с кодом `pdf_font_unavailable`.
14. `check_repository_hygiene` подтверждает, что `docs/superpowers/plans/` не отслеживается.

После каждой фазы выполняется `make check` и `make test-e2e`. Дополнительно:

- после фазы 1 — `python -m scripts.sqlite_restore_smoke` и `make docker-build`;
- после фазы 2 — ручная проверка перемотки аудиозаписи в браузере: это цель фазы, и автотест на 206
  её не заменяет;
- после фазы 3 — визуальная проверка страниц с `<select>` и каталога вариантов в браузере.

S3-проверка `python -m scripts.s3_smoke` выполняется после фазы 2, поскольку меняется способ чтения
записей из хранилища.

## Что остаётся без изменений

Следующее рассматривалось и сознательно не входит в объём работ:

- PDF-экспорт сохраняется целиком; правится только обработка отсутствующего шрифта;
- S3-хранилище, почта, аудит-журнал, назначения со снимком материала и редактор материалов не трогаются;
- структура `content/` и формат `index.json` не меняются;
- шесть markdown-файлов в корне не объединяются: их пересечение — отдельная задача, не связанная с кодом;
- поддержка Range для S3 не добавляется.
