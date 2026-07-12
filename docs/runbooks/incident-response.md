# Incident response

## Первые 15 минут

1. Зафиксируйте время, затронутые URL, роли и request ID; не копируйте passwords, tokens, audio и cookies.
2. Проверьте `curl -fsS http://127.0.0.1:8080/api/health` и `docker compose ps`.
3. По request ID найдите JSON-лог; сравните время с app, proxy, PostgreSQL и worker logs.
4. Определите scope: availability, data loss/corruption, security exposure или деградация отдельного adapter.
5. Назначьте одного координатора и ведите timeline в закрытом incident-канале.

## Локализация

- App unhealthy: проверьте последний deploy, БД и filesystem permissions; rollback image без миграции данных допустим только при совместимой схеме.
- Database unavailable: остановите записывающие процессы, проверьте disk/connections и восстанавливайте в новую БД по runbook backup/restore.
- Storage unavailable: остановите worker, не удаляйте metadata записей, проверьте bucket endpoint, permissions и provider status.
- Worker backlog: остановите повторы при provider outage, сохраните queue и возобновите worker после smoke.
- Suspected secret exposure: отзовите и ротируйте ключ у provider, обновите secret manager/`.env`, перезапустите сервисы и проверьте audit. Не публикуйте сам секрет в incident-отчёте.

## Восстановление и закрытие

Перед возвратом traffic проверьте health, login, чтение/запись БД, одну аудиозапись, worker `--once` и свежий backup. Наблюдайте счётчики 4xx/5xx и
очередь worker.

В postmortem зафиксируйте impact, timeline, root cause, факторы обнаружения/восстановления и конкретные follow-up actions с владельцами и сроками.
