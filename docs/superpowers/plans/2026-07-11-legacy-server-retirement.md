# Legacy Server Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать FastAPI единственным основным runtime и перенести compatibility HTTP server в изолированный `legacy/`.

**Architecture:** Основные тесты и CI работают только через `trainer` и `asgi.py`. Старый HTTP runtime и его end-to-end-тест сохраняются в `legacy/` для ручной проверки до следующего стабильного релиза.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, unittest, coverage.py, GitHub Actions.

## Global Constraints

- Не менять API и пользовательские сценарии.
- Не оставлять корневой compatibility shim `server.py`.
- Не запускать legacy-тесты из `make test`, `make check` и CI.
- Сохранить coverage threshold 70% для package `trainer`.
- Сохранить legacy-реализацию на один стабильный релизный цикл.

---

### Task 1: Отвязать основные тесты от `server.py`

**Files:**
- Modify: `tests/integration/test_asgi.py`
- Modify: `tests/integration/test_materials.py`
- Modify: `tests/unit/test_package_layout.py`

**Interfaces:**
- Consumes: `trainer.api.runtime.DATA_DIR`, `DB_PATH`, `AUDIO_DIR`, `connect()`.
- Produces: основной test suite, который не импортирует `server` или `legacy.server`.

- [ ] Заменить `server.DATA_DIR`, `server.DB_PATH`, `server.AUDIO_DIR` в FastAPI fixtures на локальные `root`, `database_path`, `audio_dir` и присваивать их `runtime`, `dependencies`, `materials`, `recordings`.
- [ ] Заменить `server.connect()` в materials test на `runtime.connect()`.
- [ ] Заменить package-layout test импорта `server` на проверки `not (root / "server.py").exists()`, `(root / "legacy/server.py").is_file()` и отсутствия `legacy.server` в `sys.modules` после импорта FastAPI/worker.
- [ ] Запустить `PYTHONPATH=src make test-unit test-integration`; ожидать PASS без legacy-импортов.

### Task 2: Изолировать compatibility runtime

**Files:**
- Move: `server.py` → `legacy/server.py`
- Move and adapt: `tests/integration/test_server.py` → `tests/integration/test_api_flows.py`
- Create: `legacy/tests/test_server.py`
- Create: `legacy/__init__.py`
- Create: `legacy/tests/__init__.py`
- Create: `legacy/README.md`

**Interfaces:**
- Consumes: текущая `TrainerHandler` и `main()` без изменения HTTP-поведения.
- Produces: `legacy.server`, FastAPI API-flow coverage и ручная команда `PYTHONPATH=src python -m legacy.server`.

- [ ] Перенести runtime без изменения handler-логики; API-flow сценарии перевести на FastAPI `TestClient`, а в legacy-тесте оставить health smoke через `from legacy import server`.
- [ ] Описать в `legacy/README.md` запуск `PYTHONPATH=src python -m legacy.server --host 127.0.0.1 --port 8080` и ручную проверку `PYTHONPATH=src python -m unittest discover -s legacy/tests -v`.
- [ ] Запустить ручную legacy-проверку; ожидать прежние legacy-сценарии PASS.

### Task 3: Закрепить FastAPI-only workflow

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `DEVELOPMENT.md`
- Modify: `AGENTS.md`
- Modify: `docs/architecture.md`
- Modify: `docs/decisions/0001-fastapi-runtime.md`

**Interfaces:**
- Consumes: `asgi:app`, `/api/health`, текущие CI services.
- Produces: FastAPI smoke-check и единая documented production-точка запуска.

- [ ] Убрать `server` из `[tool.coverage.run].source`, оставив `source = ["trainer"]`.
- [ ] Добавить CI-шаг, который запускает `python -m uvicorn asgi:app --host 127.0.0.1 --port 8080`, ждёт `curl -fsS http://127.0.0.1:8080/api/health` и гарантированно останавливает процесс через shell `trap`.
- [ ] Обновить документы: FastAPI — единственный основной runtime; legacy-запуск описан только в `legacy/README.md`; удаление `legacy/` допустимо после стабильного релизного цикла.
- [ ] Проверить `rg`-поиском, что вне `legacy/` нет `import server`, `from server` и инструкций запуска legacy.
- [ ] Запустить `PYTHONPATH=src make check`, FastAPI smoke-check и `PYTHONPATH=src make test-e2e`; ожидать PASS и coverage не ниже 70%.
