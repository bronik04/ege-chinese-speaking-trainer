PYTHON ?= .venv/bin/python
PYTHON_BOOTSTRAP ?= python3
NPM ?= npm
HOST ?= 127.0.0.1
PORT ?= 8080

PYTHON_BIN_DIR := $(abspath $(dir $(PYTHON)))

.PHONY: install run lint test test-e2e check docker-check docker-build ensure-python

ensure-python:
	@if ! command -v "$(PYTHON)" >/dev/null 2>&1 && [ ! -x "$(PYTHON)" ]; then \
		echo "Python environment not found at $(PYTHON). Run 'make install' first." >&2; \
		exit 1; \
	fi

install:
	@if [ ! -x "$(PYTHON)" ]; then $(PYTHON_BOOTSTRAP) -m venv .venv; fi
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pip install --no-deps --no-build-isolation -e .
	$(NPM) ci

run: ensure-python
	$(PYTHON) -m uvicorn asgi:app --host $(HOST) --port $(PORT)

lint: ensure-python
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(NPM) run lint
	$(PYTHON) -m scripts.check_json

test: ensure-python
	$(NPM) test
	$(PYTHON) -m coverage erase
	$(PYTHON) -m coverage run -m unittest discover -s tests -v
	$(PYTHON) -m coverage report

test-e2e: ensure-python
	$(NPM) run test:e2e

check: ensure-python
	PATH="$(PYTHON_BIN_DIR):$$PATH" $(PYTHON) -m pre_commit run --all-files
	$(MAKE) test PYTHON="$(PYTHON)" NPM="$(NPM)"

docker-check:
	@set -e; \
	created_env=0; \
	if [ ! -f .env ]; then cp .env.example .env; created_env=1; fi; \
	trap 'if [ "$$created_env" = 1 ]; then rm -f .env; fi' EXIT; \
	docker compose -f compose.yml config --quiet; \
	docker compose -f compose.yml -f compose.scale.yml config --quiet

docker-build:
	docker build -t chinese-speaking-trainer:test .
