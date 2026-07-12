# Завершение структурного рефакторинга

## Цель

Закрыть оставшиеся части задач 2–4 исходного плана без изменения HTTP API, пользовательского поведения, схемы БД
и frontend. Итоговая структура должна отражать реальные ответственности, а не буквальное дерево пустых пакетов.

## Архитектурное решение

- `trainer.domain.accounts` становится пакетом с чистыми правилами credentials, password/token и доступа по ролям;
  allowlist передаётся явно с границы API и не читается из environment внутри domain.
- `trainer.infrastructure.mailer`, `storage` и `observability` становятся пакетами и сохраняют прежние импорты через
  `__init__.py`.
- `trainer.services` оркестрирует сессии, account links и операции с приватными storage-объектами.
- API dependencies переводит domain-решения в HTTP-ответы, но не выполняет SQL и не выбирает SMTP/storage adapter.
- Контроллеры recordings, assignments и account cleanup вызывают прикладные storage-сервисы.

Публичные Python-импорты остаются совместимыми. Новые domain-решения не содержат HTTP-статусов или infrastructure
imports. Пакеты без реального содержимого не создаются.

## Quality gate и проверка

Pre-commit и `make lint` проверяют YAML syntax. Docker Compose остаётся отдельным `make docker-check`, обязательным в
CI, чтобы базовый `make check` не требовал локального Docker daemon. Архитектурные unit-тесты запрещают возврат SQL,
mailer и storage factory в API dependencies, а integration/E2E-тесты фиксируют совместимость поведения.
