# Архитектура тренажёра

## Обзор

Браузерный frontend на vanilla JavaScript обращается к FastAPI-приложению через JSON API. FastAPI запускается через `asgi.py`, проверяет запросы и передаёт прикладные сценарии контроллерам. Приложение поддерживает SQLite локально и PostgreSQL в scale-профиле, локальное или S3/R2-хранилище, SMTP/outbox и отдельный worker транскрибации.

Архитектурные решения зафиксированы в [ADR 0001](decisions/0001-fastapi-runtime.md) и [ADR 0002](decisions/0002-content-and-runtime-data.md).

## Текущая структура

```text
src/trainer/main.py  FastAPI application и статическая выдача
asgi.py              совместимый ASGI wrapper
server.py            legacy HTTP runtime
src/trainer/api/      HTTP, schemas и controllers
src/trainer/domain/         чистые бизнес-правила
src/trainer/services/       прикладные сервисы
src/trainer/infrastructure/ БД и внешние adapters
src/trainer/workers/  фоновые процессы
js/ + *.html/*.css    браузерный frontend
data/                 версионируемые JSON-материалы
assets/               публичные изображения
migrations/           Alembic-миграции PostgreSQL
scripts/              backup, smoke checks и worker
tests*/               Python, JavaScript и Playwright
deploy/               Caddy и nginx
```

Контроллеры отвечают за HTTP-оркестрацию, domain — за чистые правила, services — за прикладные операции, infrastructure — за SQL и внешние интеграции. Зависимости domain не направляются в API или infrastructure.

## Целевая структура

```text
src/trainer/
├── api/                 HTTP, schemas, dependencies, errors
├── domain/              аккаунты, материалы, назначения, оценивание
├── infrastructure/      database, storage, mailer, observability, OpenAI
├── workers/             фоновые процессы
├── config.py
└── main.py
frontend/
├── pages/
├── js/
├── styles/
└── assets/
content/
├── variants/
└── reference/
public/                  напрямую раздаваемые файлы
docs/                    архитектура, ADR и runbooks
tests/                   unit и integration
tests-e2e/               браузерные сценарии
var/                     локальные runtime-данные
backups/                 резервные копии
tmp/                     воспроизводимые временные файлы
```

Это направление миграции, а не разрешение заранее создавать пустые каталоги или дублирующие модули.

## Границы и зависимости

Целевое направление: `API → domain → infrastructure interfaces`.

- API знает HTTP, Pydantic, cookies, status codes и JSON-контракт.
- Domain описывает правила ролей, материалов, назначений, попыток и оценивания без зависимости от FastAPI.
- Infrastructure реализует SQL, filesystem, S3/R2, SMTP, PDF, observability и OpenAI.
- Worker вызывает domain-сценарий и infrastructure adapters, но не импортируется API ради фонового выполнения.
- Frontend зависит только от публичного HTTP-контракта и публичных assets.

Domain может задавать interface/Protocol для хранилища или внешнего сервиса. Конкретный adapter передаётся на границе приложения; domain не выбирает S3, SMTP или модель OpenAI через environment напрямую.

## Поток данных

```text
Browser
  → FastAPI route и Pydantic validation
  → authentication/authorization dependency
  → domain operation
  → database и/или storage interface
  → SQLite/PostgreSQL, local storage или S3/R2
  → единый API response с requestId
```

Для транскрибации запись сначала сохраняется в закрытом storage и устойчивой очереди БД. Отдельный worker забирает задание, скачивает объект через storage adapter, вызывает OpenAI и записывает результат или состояние повторной попытки. SMTP следует тому же принципу: domain запрашивает отправку, mailer adapter использует SMTP или приватный локальный outbox.

## Категории файлов

| Категория | Назначение | Git | Публичный доступ |
|---|---|---:|---:|
| `content/` (сейчас `data/`) | проверяемые учебные материалы | да | только через разрешённый API |
| `public/` (сейчас часть `assets/`) | браузерные изображения и стили | да | да |
| `var/` | SQLite, аудио, material assets, outbox | нет | нет |
| `backups/` | резервные копии БД и файлов | нет | нет |
| `tmp/` | восстанавливаемые промежуточные результаты | нет | нет |

Секреты находятся только в environment/secret manager. `.env.example` документирует имена переменных, но не содержит реальные значения.

## Стратегия перехода

1. Сначала фиксируются правила и тесты текущего поведения.
2. Затем вводится единый command layer и package metadata.
3. Python-модули размещены в пакете `src/trainer` с совместимым `asgi.py`; следующим этапом backend делится по обязанностям.
4. После стабилизации backend переносятся frontend, content и public assets с сохранением URL.
5. Миграции SQLite/PostgreSQL унифицируются отдельной задачей.
6. `server.py` удаляется только после подтверждения отсутствия потребителей legacy runtime.

Каждый шаг должен завершаться рабочим приложением и самостоятельным commit. Массовое перемещение backend, frontend и данных в одном изменении не допускается.

## Где размещать изменения

| Изменение | Сейчас | Цель | Обязательная проверка |
|---|---|---|---|
| HTTP endpoint или schema | `src/trainer/api` | `src/trainer/api` | Python integration test и OpenAPI contract |
| Бизнес-правило | `src/trainer/domain` | `src/trainer/domain` | независимый unit test |
| SQL или migration | `src/trainer/infrastructure/database`, `migrations/` | `src/trainer/infrastructure/database` | чистая и обновляемая БД |
| S3/filesystem/SMTP/OpenAI | `src/trainer/infrastructure` | `src/trainer/infrastructure` | adapter unit test и smoke test |
| UI rendering | `js/`, HTML/CSS в корне | `frontend/` | JS test; Playwright для сценария |
| Вариант или справочник | `data/` и `assets/variants` | `content/` и `public/` | JSON check и профильный content test |
| Worker или backup | `scripts/` | `workers/` или `scripts/` | unit/integration test и dry-run/smoke |

Правила безопасной работы с данными находятся в [SECURITY.md](../SECURITY.md), а пошаговый workflow — в [CONTRIBUTING.md](../CONTRIBUTING.md).
