# Backup and restore

## Что копируется

Локальный backup содержит SQLite `trainer.sqlite3` и архивы `audio/`, `material-assets/` и
`assignment-assets/`. `assignment-assets/` сохраняет историческое физическое имя и содержит приватные
snapshot-изображения; каталог обязателен при восстановлении экземпляра, на котором создавались review requests.

Для S3/R2 включите versioning или provider backup: `scripts/backup.py` не копирует bucket. Backup хранится вне
хоста приложения и имеет не менее строгие права, чем production storage. `.env` и credentials в него не входят.

## Создание

Локально:

```bash
.venv/bin/python -m scripts.backup --data-dir var --output-dir backups --keep 14
```

В Docker:

```bash
docker compose exec app python -m scripts.backup --data-dir /app/var --output-dir /app/backups --keep 14
```

После создания перенесите timestamp-каталог на другой хост и зафиксируйте checksum.

## Восстановление

1. Остановите app и сохраните текущий `var/` как rollback-копию.
2. Восстанавливайте в новый пустой каталог, не поверх рабочей директории.
3. Скопируйте `trainer.sqlite3` и распакуйте имеющиеся `audio.tar.gz`, `material-assets.tar.gz` и
   `assignment-assets.tar.gz`. Старый backup может не содержать более новые каталоги, но файл БД обязателен.
4. Выполните `PRAGMA integrity_check` и проверьте владельца/права файлов.
5. Переключите `TRAINER_DATA_DIR`, запустите app и проверьте `/api/health`, вход, каталог, одну запись и одно
   snapshot-изображение в review request.

Автоматизированный smoke того же потока:

```bash
.venv/bin/python -m scripts.sqlite_restore_smoke
```

Если проверка не прошла, не перезаписывайте исходный `var/`: верните прежний каталог и сохраните логи причины.
