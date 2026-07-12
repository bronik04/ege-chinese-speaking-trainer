# Вывод legacy `server.py` из основного пути

## Цель

Сделать FastAPI через `asgi.py` единственным основным runtime, убрать зависимость основных тестов и CI от
корневого `server.py`, но сохранить legacy-реализацию на один стабильный релизный цикл.

## Структура и границы

- Корневой `server.py` переезжает в `legacy/server.py`; compatibility shim в корне не остаётся.
- API-контрактные сценарии из `tests/integration/test_server.py` переезжают в `tests/integration/test_api_flows.py` и выполняются через FastAPI `TestClient`.
- `legacy/tests/test_server.py` сохраняет ручной smoke legacy HTTP transport и импортирует `legacy.server`.
- `legacy/README.md` описывает только ручной запуск и transport smoke legacy-слоя. Эти команды не входят в
  `make test`, `make check` и CI.
- Основной Python coverage считает только package `trainer`; legacy-код не влияет на порог 70%.

## Основные тесты

- FastAPI-тесты настраивают временные `DATA_DIR`, `DB_PATH` и `AUDIO_DIR` через `trainer.api.runtime` и не импортируют legacy.
- Прямой доступ к тестовой БД в тестах материалов идёт через `runtime.connect()`.
- Package-layout test проверяет отсутствие корневого `server.py`, наличие `legacy/server.py` и то, что импорт FastAPI и worker
  не загружает `legacy.server`.
- CI отдельно поднимает Uvicorn через `asgi:app` и проверяет `/api/health`; остальные unit, integration, E2E, PostgreSQL,
  S3 и Docker-проверки сохраняются.

## Документация и удаление

`README.md`, `DEVELOPMENT.md`, `AGENTS.md`, `docs/architecture.md` и ADR фиксируют, что основной runtime — FastAPI, а legacy-код не является
частью обычного workflow. После одного стабильного релизного цикла `legacy/` можно удалить отдельным изменением после
повторного прохождения основных и E2E-тестов.
