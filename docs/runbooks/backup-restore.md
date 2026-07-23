# Backup and restore

## Что копируется

- SQLite: `trainer.sqlite3`, `audio/`, `material-assets/` и `assignment-assets/` (копии изображений в снимках назначений).
- PostgreSQL: custom-format `trainer.pgdump`; аудио и assets резервируются отдельно согласно storage backend.
- S3/R2: включите versioning или provider backup; `scripts/backup.py` не копирует bucket.

Backup должен храниться вне хоста приложения. Пароли БД, AWS keys и `.env` в backup не включаются.

## Создание

SQLite в Docker:

```bash
docker compose exec app python scripts/backup.py --data-dir /app/var --output-dir /app/backups --keep 14
```

PostgreSQL использует `DATABASE_URL` и `pg_dump` из image:

```bash
docker compose -f compose.yml -f compose.scale.yml exec app python scripts/backup.py --data-dir /app/var --output-dir /app/backups --keep 14
```

После создания перенесите timestamp-каталог на другой хост и зафиксируйте checksum.

## Восстановление SQLite

1. Остановите app и worker.
2. Сохраните текущий `var/` как rollback-копию.
3. В пустом каталоге разместите `trainer.sqlite3` и распакуйте `audio.tar.gz`, `material-assets.tar.gz` и `assignment-assets.tar.gz`. Обязателен только файл БД: копия, снятая до появления очередного архива, восстанавливается без него.
4. Проверьте `PRAGMA integrity_check`, права файлов и наличие аудио/assets.
5. Запустите app, проверьте `/api/health`, вход, каталог, одну аудиозапись и изображение задания в выданном назначении.

Автоматизированная проверка того же потока:

```bash
python -m scripts.sqlite_restore_smoke
```

## Восстановление PostgreSQL

Восстанавливайте в новую пустую БД через `pg_restore --no-owner`, проверьте Alembic head, таблицы и контрольные записи, затем
переключайте `DATABASE_URL`. Проверка на отдельной тестовой БД:

```bash
TEST_DATABASE_URL=postgresql://trainer:password@127.0.0.1:5432/trainer_test python -m scripts.postgres_restore_smoke
```

Если проверка не прошла, не перезаписывайте исходную БД: верните прежний `DATABASE_URL`/каталог и зафиксируйте причину.
