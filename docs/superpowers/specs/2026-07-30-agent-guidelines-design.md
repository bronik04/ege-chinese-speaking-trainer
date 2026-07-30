# Гайдлайн по моделям, effort и скиллам для AI-агентов

## Цель

Дать AI-агентам, работающим в этом репозитории, ориентир: какую модель Claude и какой уровень reasoning effort
выбирать под тип задачи, и какие плагины/скиллы реально относятся к проекту. Документ адресован агентам, не
конечным пользователям тренажёра.

## Расположение

Новый файл `docs/agent-guidelines.md`, на который [CLAUDE.md](../../../CLAUDE.md) добавляет ссылку в первый абзац —
рядом с AGENTS.md/DEVELOPMENT.md/architecture.md/SECURITY.md. Отдельный файл, а не раздел AGENTS.md, потому что
AGENTS.md — обязательные архитектурные границы, а этот документ — рекомендация по инструментам, которая может
меняться независимо и чаще.

## Содержание документа

### Раздел 1 — модель и effort по типу задачи

Таблица категорий, построенная на реальных границах проекта (AGENTS.md «Как вносить изменения», SECURITY.md
«Security-sensitive области», architecture.md «Где размещать изменения»):

- механические правки (Haiku 4.5, low);
- обычная разработка в существующем слое — route/controller/service, JS-модуль, тест (Sonnet 5, medium);
- domain-правила, границы слоёв, Alembic-миграции (Sonnet 5, high);
- security-sensitive зоны из SECURITY.md — accounts, storage, mailer, transcription, auth, deploy (Opus 5,
  high/xhigh);
- ревью перед мержем и security-review (Opus 5, xhigh);
- отладка непрозрачного бага, systematic-debugging (Opus 5, high);
- контент/задания ЕГЭ через скилл ege-chinese (Sonnet 5, high; Opus 5 для спорных формулировок);
- документация (Sonnet 5, medium).

Плюс одна заметка: глобальный дефолт окружения — `model: opus`, `effortLevel: xhigh`; документ объясняет, когда
осмысленно явно понижать до Sonnet/Haiku ради скорости на рутинных задачах, а не когда это обязательно.

### Раздел 2 — плагины и скиллы, относящиеся к проекту

Две группы, потому что управляются они по-разному:

1. Локальные плагины `claude-plugins-official` (видны в `~/.claude/plugins/installed_plugins.json`):
   `superpowers` и `frontend-design` — релевантны и остаются включены; `typescript-lsp` и `swift-lsp` — в проекте
   нет TypeScript и Swift (frontend на vanilla JS без сборки), отключаются; `preset-cli-skills` уже выключен.
2. Встроенный набор скиллов текущего окружения (Cowork: `anthropic-skills:*`, `design:*`, `operations:*`,
   `productivity:*`, `dataviz`, `cowork-plugin-management` и т.д.) — не управляется файлами репозитория. Документ
   перечисляет, что из этого набора уместно при работе над проектом (например `ege-chinese` — контент ЕГЭ,
   `dataviz` — разовые графики прогресса, если понадобятся), и явно отмечает, что отключение остального делается
   только через настройки самого Cowork/claude.ai, не через `.claude/settings.json`.

## Реализация отключения плагинов

`typescript-lsp` и `swift-lsp` отключаются не в `~/.claude/settings.json` (это глобально задело бы другие проекты
пользователя на TS/Swift), а в новом закоммиченном `.claude/settings.json` этого репозитория:

```json
{
  "enabledPlugins": {
    "typescript-lsp@claude-plugins-official": false,
    "swift-lsp@claude-plugins-official": false
  }
}
```

Файл трекается в Git (в отличие от `.claude/settings.local.json`), поэтому настройка одинакова для всех, кто
работает над репозиторием агентами Claude Code.

## Вне рамок

Документ не переопределяет обязательные правила AGENTS.md/SECURITY.md — это рекомендация по инструментам, а не
gate вроде `make check`. Не создаём смены модели/effort как автоматизацию (хуки) — выбор остаётся за агентом,
читающим документ.
