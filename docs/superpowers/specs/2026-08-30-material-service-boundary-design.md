# Граница service/repository для материалов

## Контекст

`src/trainer/api/controllers/materials.py` обслуживает девять публичных сценариев, но одновременно разбирает
transport-значения, проверяет предметные правила, читает официальный каталог, выполняет SQL, управляет
транзакциями, преобразует изображения через Pillow, выбирает storage backend, пишет и удаляет объекты и создаёт
audit events. Из-за этого HTTP-слой нельзя тестировать отдельно от SQLite и файлового хранилища, а изменение
правил публикации требует правок в контроллере.

Эта итерация выделяет одну вертикальную границу материалов по уже проверенному в проекте шаблону review
requests. Публичные HTTP-контракты, схема БД, официальный контент и frontend остаются без изменений.

## Цели

- Удалить из material controller прямые database imports, `connect()`, `.execute()`, Pillow и выбор storage.
- Оставить в controller только адаптацию API-входов, semantic error mapping и `ActionResult`/`FileResult`.
- Перенести девять прикладных сценариев в transport-независимый `MaterialService`.
- Определить один высокоуровневый `MaterialRepository` port и SQLite-реализацию.
- Сохранить существующие транзакции, audit events, правила видимости, форматы ответов и storage keys.
- Зафиксировать границу архитектурными, unit- и integration-тестами.

## Не входит в задачу

- Изменение routes, URL, Pydantic schemas или JSON-ответов.
- Изменение таблиц, индексов, миграций или frozen SQLite baseline.
- Изменение редактора материалов, каталога или других frontend-сценариев.
- Изменение экзаменационных правил `build_content()` и `material_asset_ids()`.
- Изменение политики хранения: удаление неиспользуемых assets после публикации остаётся best effort.
- Переработка auth, groups, recordings, personal recordings или review requests.
- Универсальный dependency-injection framework или общий ORM/UoW для всего приложения.
- Перевод material asset download на `file_response()` и изменение cache/range-поведения.

## Рассмотренные варианты

### 1. Перенести SQL в существующий `services/materials.py`

Это минимальный diff, но service продолжит принимать SQLite connection и импортировать database helpers.
Контроллер станет короче, однако стабильной прикладной границы и дешёвых unit-тестов не появится.

### 2. Разделить материалы, assets, публикацию и каталог на отдельные repositories

Такое разделение возможно, но текущие сценарии совместно изменяют одни таблицы и используют одну транзакцию.
Несколько ports усложнят координацию без реальной второй реализации или отдельного bounded context.

### 3. Один `MaterialRepository` с transaction/session port — выбранный вариант

Service получает операции предметного уровня и не видит connection/cursor. SQLite adapter владеет SQL,
commit/rollback и audit persistence. Для текущего объёма это минимальная полноценная граница, аналогичная
review-request boundary, но без общего framework.

## Архитектура

```text
materials route
  → materials controller
    → MaterialService
      → MaterialRepository port
        → SQLiteMaterialRepository
      → MaterialAssetStorage port
      → image encoder callable
```

### API controller

`src/trainer/api/controllers/materials.py` сохраняет имена и сигнатуры девяти публичных функций:

- `materials_list`;
- `materials_mine`;
- `material_get`;
- `material_create`;
- `material_update`;
- `material_publish`;
- `material_delete`;
- `material_asset_create`;
- `material_asset_get`.

Controller преобразует user/context/payload в простые service dataclasses, вызывает factory из
`trainer.api.runtime`, преобразует `MaterialError` в прежние `ApiError` code/message/status и формирует прежний
`ActionResult` либо `FileResult`. В нём нет SQL, database imports, Pillow, временных файлов и выбора storage.

### Application service

`src/trainer/services/materials.py` расширяется до `MaterialService`. Сервис зависит только от domain rules,
standard library и ports из `src/trainer/services/material_repository.py`. Он отвечает за:

- официальный и пользовательский каталог;
- правила видимости detail;
- нормализацию metadata и semantic validation;
- создание, изменение, публикацию и архивирование;
- проверку принадлежности используемых изображений;
- вычисление assets, которые можно удалить после публикации;
- проверку MIME/размера, вызов image encoder и storage orchestration;
- компенсационное удаление нового storage object при ошибке metadata insert;
- возврат приватной ссылки на asset только авторизованному пользователю.

Сервис выбрасывает `MaterialError(reason, message=None)`. HTTP-коды и API error codes остаются в controller.
`official_index`, `official_detail` и `public_official_index` остаются чистыми filesystem helpers рядом с
сервисом. Неиспользуемый `assignment_material(root, database, material_id)` удаляется: внутри проекта его никто
не вызывает, а сохранение функции с raw connection нарушало бы новую границу.

### Ports

`src/trainer/services/material_repository.py` определяет immutable dataclasses и Protocols:

- `MaterialActor(id, email, email_verified)`;
- `MaterialMetadata(slug, kind, task_number, title, year, source, content)`;
- `MaterialRecord` с полями, необходимыми правилам и formatters;
- `MaterialAssetRecord(id, material_id, storage_key, mime_type, size_bytes)`;
- `MaterialAudit(actor, action, client_ip, user_agent, details)`;
- `MaterialImageError` как adapter-neutral ошибка декодирования/преобразования изображения;
- `MaterialRepository` для read operations и `transaction()`;
- `MaterialRepositorySession` для атомарных mutations и audit;
- `MaterialAssetStorage` с `put()` и `delete()`.

Port не импортирует `sqlite3`, API, Pillow или infrastructure modules и не раскрывает connection/cursor.
Repository methods выражают намерения: получить опубликованные/свои материалы, найти материал/asset, создать или
изменить draft, загрузить материал владельца, проверить принадлежащие asset ids, получить assignment snapshots,
опубликовать, удалить metadata неиспользуемых assets, архивировать, добавить asset и записать audit.

Конфликт slug представлен отдельным `MaterialConflictError` из port. SQLite adapter преобразует supported
integrity exceptions в него, поэтому service не знает о конкретном database driver.

### SQLite adapter

`src/trainer/infrastructure/database/material_repository.py` реализует port поверх существующей connection
factory. Adapter владеет всем material SQL, row mapping, commit/rollback и вызовом существующего audit helper.

Read methods открывают и закрывают собственное соединение. `transaction()` открывает соединение, возвращает
session, делает commit при успехе, rollback при исключении и всегда закрывает connection. Публикация выполняется
в одной transaction: чтение owner material, проверка asset ownership, обновление content/status, выбор и удаление
metadata неиспользуемых assets и `material_published` audit.

### Runtime composition

`src/trainer/api/runtime.py` добавляет не кэшируемую factory `material_service()`. Она собирает:

- `SQLiteMaterialRepository(connect)`;
- storage из `storage_from_env(MATERIAL_ASSET_DIR)`;
- project root, material asset root и temporary root;
- текущий editor allowlist и лимит изображения;
- Pillow encoder из infrastructure.

Factory не кэшируется, чтобы тестовые fixtures могли менять `DB_PATH`, directories и environment между
сценариями так же, как сейчас.

### Image encoder

Pillow-детали переносятся в `src/trainer/infrastructure/images.py`. Чистая функция принимает bytes, загружает
изображение, проверяет минимум 320×240 и максимум 20 млн пикселей, уменьшает до 1600×1600, приводит режим к
RGB/RGBA и возвращает WebP bytes с прежними quality/method. Ожидаемые ошибки преобразуются в
`MaterialImageError` из service port, который service переводит в semantic `invalid_image`; неожиданные ошибки
не маскируются.

## Потоки данных

### Каталог и detail

1. Controller преобразует optional user в `MaterialActor`.
2. Service читает официальный каталог с прежним guest-фильтром `open-2026`.
3. Для authenticated catalog service добавляет опубликованные пользовательские материалы из repository.
4. `canCreate` вычисляется по прежнему `editor_allowed()` и текущему allowlist.
5. Detail сначала проверяет официальный материал, затем пользовательский и применяет прежние visibility rules.

### Создание и изменение

1. Service нормализует slug, kind/task, title/year/source и ограничивает сериализованное content 150 000
   символами.
2. Создание пишет draft и `material_created` audit в одной transaction.
3. Изменение доступно только владельцу, всегда возвращает материал в draft и очищает `published_at`.
4. Конфликт slug превращается в semantic `slug_exists`.

### Публикация

1. Service в transaction загружает материал владельца.
2. `build_content()` строит каноническое содержание, `material_asset_ids()` извлекает все URL assets.
3. Session подтверждает, что каждый asset принадлежит материалу.
4. Service читает assignment snapshots и сохраняет все asset ids, используемые в неизменяемых снимках.
   Некорректные historical snapshots по-прежнему игнорируются.
5. Session обновляет content/status/timestamps, удаляет metadata только assets, не используемых новым content или
   assignment snapshots, и пишет `material_published` audit.
6. После commit service best-effort удаляет соответствующие storage objects. Ошибка physical delete не отменяет
   успешную публикацию, как и сейчас.

### Загрузка изображения

1. Service отклоняет неподдерживаемый MIME и body вне прежнего диапазона
   `1..min(MAX_AUDIO_BODY, 5_000_000)` до вызова encoder/storage.
2. Repository подтверждает существование материала владельца и возвращает numeric id.
3. Encoder проверяет изображение и возвращает WebP bytes.
4. Service создаёт прежний key `materials/{material_id}/{token}.webp`, пишет временный файл и вызывает storage.
5. После успешного storage put service в transaction добавляет metadata.
6. При любой ошибке после формирования key service best-effort удаляет новый storage object; временный файл
   удаляется всегда.
7. Ответ сохраняет `/api/material-assets/{id}` и status 201.

## Ошибки и совместимость API

Controller сохраняет текущие mapping и русские сообщения:

- `invalid_metadata` → `invalid_material`, 400, исходное сообщение validation;
- `slug_exists` → `material_slug_exists`, 409;
- `not_found` → `material_not_found`, 404;
- `incomplete` → `material_incomplete`, 400, исходное сообщение domain validation;
- `foreign_asset` → `invalid_material_asset`, 400;
- `unsupported_image` → `unsupported_image`, 415;
- `image_too_large` → `image_too_large`, 413;
- `invalid_image` → `invalid_image`, 422;
- `asset_not_found` → `asset_not_found`, 404.

Неожиданные database/storage ошибки не маскируются и продолжают попадать в общий 500 contract. Публичные payloads,
status codes, audit action names/details и storage keys не меняются.

## Тестирование

1. `tests/unit/test_material_service.py` использует stateful fake repository, fake storage и injected encoder.
   Тесты фиксируют visibility, metadata validation, create/update, publication asset retention, archive, upload
   compensation и private asset access без HTTP/SQLite.
2. `tests/integration/test_material_repository.py` использует временную мигрированную SQLite DB и проверяет read
   ordering, commit/rollback, slug conflict, publication mutation, asset metadata и audit.
3. `tests/integration/test_materials.py` продолжает фиксировать все HTTP-контракты. Test seam для metadata failure
   переносится с patch controller globals на runtime composition/repository factory без ослабления assertion об
   удалении storage object.
4. `tests/unit/test_architecture_boundaries.py` запрещает material controller database/storage/Pillow access,
   service imports из API/database implementation и infrastructure imports в port.
5. `docs/architecture.md` получает отдельную vertical boundary материалов.
6. Итоговая обязательная проверка — `make check`. UI не меняется, поэтому `make test-e2e` не требуется.

## Последовательность реализации

1. Добавить ports и failing unit/architecture tests.
2. Реализовать read scenarios и SQLite read adapter.
3. Перенести нормализацию, create и update.
4. Перенести publish/archive с transaction и assignment asset retention.
5. Вынести Pillow encoder и перенести upload/download metadata orchestration.
6. Свести controller к transport/error mapping, добавить runtime composition.
7. Обновить integration tests и документацию, выполнить полную проверку и code review.

## Критерии готовности

- Material controller не импортирует database/storage/Pillow и не содержит `connect()`, `.execute()` или
  filesystem writes.
- `MaterialService` не импортирует `trainer.api` или database implementation modules.
- Material repository port не импортирует `sqlite3` или `trainer.infrastructure`.
- SQLite adapter не импортирует `trainer.api`.
- Все девять публичных controller signatures и HTTP-контракты сохранены.
- Publication остаётся атомарной на уровне SQLite и сохраняет assets из assignment snapshots.
- Upload удаляет новый storage object при metadata failure и всегда удаляет временный файл.
- Схема БД, migrations, frontend и официальный content не изменены.
- `make check` завершён с нулевым кодом.
