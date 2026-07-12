# Legacy HTTP server

Этот runtime сохранён только на один стабильный релизный цикл. Основное приложение запускается через FastAPI и
`asgi.py`; новые возможности в legacy-сервер не добавляются.

Ручной запуск:

```bash
PYTHONPATH=src python -m legacy.server --host 127.0.0.1 --port 8080
```

Ручная проверка legacy-сценариев:

```bash
PYTHONPATH=src python -m unittest discover -s legacy/tests -v
```

Эти тесты не входят в `make test`, `make check` и CI. Каталог `legacy/` можно удалить после одног стабильного релизного цикла и
повторного прохождения основных и E2E-тестов.
