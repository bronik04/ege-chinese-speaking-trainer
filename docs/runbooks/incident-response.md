# Incident response

## Первые 15 минут

1. Зафиксируйте время, затронутые URL, роли и request ID; не копируйте passwords, tokens, audio и cookies.
2. Проверьте `curl -fsS http://127.0.0.1:8080/api/health` и `docker compose ps`.
3. По request ID найдите JSON-лог и сравните время с логами app и reverse proxy.
4. Запустите `.venv/bin/python -m scripts.cleanup_storage` и сохраните только итоговые счётчики
   `expired/completed/failed/pending`, если инцидент связан с файлами или retention.
5. Определите scope: availability, data loss/corruption, security exposure или деградация storage/SMTP.
6. Назначьте одного координатора и ведите timeline в закрытом incident-канале.

## Локализация

- App unhealthy: проверьте последний deploy, SQLite-файл, свободное место и filesystem permissions. Rollback
  image допустим только при совместимой схеме.
- Database unavailable: остановите записывающие запросы, сохраните `var/` и восстанавливайте backup в новый
  каталог по [runbook](backup-restore.md).
- Storage unavailable: не удаляйте metadata вручную; проверьте bucket endpoint, credentials, permissions или
  права локального каталога. После восстановления повторите `scripts.cleanup_storage`.
- SMTP unavailable: сохраните очередь пользовательских действий, восстановите provider и проверьте одно
  синтетическое письмо без публикации токена.
- Suspected secret exposure: отзовите ключ у provider, обновите secret manager/`.env`, перезапустите сервисы и
  проверьте audit. Не публикуйте секрет в incident-отчёте.

## Восстановление и закрытие

Перед возвратом traffic проверьте health, login, чтение/запись SQLite, одну аудиозапись, один review snapshot,
нулевые `failed/pending` cleanup-счётчики и свежий проверенный backup. Наблюдайте 4xx/5xx после восстановления.

В postmortem зафиксируйте impact, timeline, root cause, обнаружение, восстановление и follow-up actions с
владельцами и сроками.
