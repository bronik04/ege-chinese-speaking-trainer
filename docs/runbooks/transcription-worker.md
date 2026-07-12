# Transcription worker

## Запуск

Для worker нужны те же `DATABASE_URL`, `TRAINER_DATA_DIR` и storage credentials, что и для app, а также `OPENAI_API_KEY`. Не печатайте их в логи.

Локально:

```bash
python -m trainer.workers.transcription
```

Обработать не более одного job и завершиться:

```bash
python -m trainer.workers.transcription --once
```

В Docker:

```bash
docker compose --profile transcription up -d --build transcription-worker
docker compose logs -f transcription-worker
```

## Как работает очередь

Worker забирает доступный job, скачивает запись через выбранный storage adapter, вызывает transcription API и записывает текст. Ошибка
возвращает job на повтор; после трёх попыток job переходит в `failed`. Зависший `processing` job возвращается в очередь через 15 минут.

## Диагностика

1. Проверьте `/api/health` и доступ к БД.
2. Проверьте `transcription_jobs.status`, `attempts`, `available_at`, `locked_at` и `last_error`, не выводя аудио и credentials.
3. Для S3/R2 запустите MinIO smoke с тестовыми credentials.
4. Проверьте model/language и quota transcription provider.

Безопасная остановка:

```bash
docker compose stop transcription-worker
```

Текущий job будет возвращён механизмом stale-job recovery. Не удаляйте строки очереди вручную без backup.
